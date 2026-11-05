"""Graph objects + associations and lease tokens (plan #117, #119, #120).
Rebuilt from the published TAO (USENIX ATC 2013) and memcache-at-scale papers;
no code. `r` is a redis-py style client (hset, hgetall, zadd, zrevrangebyscore,
zcard, zrem, delete, set, get, incr).
"""
import json
import time
import uuid


class Graph:
    def __init__(self, r, ns="g"):
        self.r, self.ns = r, ns

    def _o(self, oid): return f"{self.ns}:o:{oid}"
    def _a(self, id1, atype): return f"{self.ns}:a:{id1}:{atype}"
    def _v(self, oid): return f"{self.ns}:ver:{oid}"

    # objects
    def obj_add(self, otype, data):
        oid = uuid.uuid4().hex
        self.r.hset(self._o(oid), mapping={"otype": otype, "data": json.dumps(data)})
        self.r.incr(self._v(oid))
        return oid

    def obj_get(self, oid):
        h = self.r.hgetall(self._o(oid))
        return None if not h else {"id": oid, "otype": h["otype"], "data": json.loads(h["data"])}

    def obj_update(self, oid, data):
        self.r.hset(self._o(oid), mapping={"data": json.dumps(data)})
        return self.r.incr(self._v(oid))

    def obj_delete(self, oid):
        self.r.delete(self._o(oid))
        self.r.incr(self._v(oid))

    # associations: time-ordered edge lists
    def assoc_add(self, id1, atype, id2, t=None, inverse=None):
        self.r.zadd(self._a(id1, atype), {id2: t if t is not None else time.time()})
        if inverse:
            self.r.zadd(self._a(id2, inverse), {id1: t if t is not None else time.time()})
        return self.r.incr(self._v(id1))

    def assoc_delete(self, id1, atype, id2, inverse=None):
        self.r.zrem(self._a(id1, atype), id2)
        if inverse:
            self.r.zrem(self._a(id2, inverse), id1)
        return self.r.incr(self._v(id1))

    def assoc_range(self, id1, atype, offset=0, limit=50):
        return self.r.zrevrangebyscore(self._a(id1, atype), "+inf", "-inf", start=offset, num=limit)

    def assoc_time_range(self, id1, atype, high, low, limit=50):
        return self.r.zrevrangebyscore(self._a(id1, atype), high, low, start=0, num=limit)

    def assoc_count(self, id1, atype):
        return self.r.zcard(self._a(id1, atype))

    # 119: read-after-write: callers pass the version they wrote; stale replica reads are refused
    def version(self, oid):
        return int(self.r.get(self._v(oid)) or 0)

    def fresh_enough(self, oid, min_version):
        return self.version(oid) >= min_version


class Leases:
    """#120: on miss, one caller gets a lease token and fills; others back off.
    A delete (invalidation) voids outstanding leases so stale fills are dropped."""
    def __init__(self, r, ttl=10):
        self.r, self.ttl = r, ttl

    def get(self, key):
        v = self.r.get(key)
        if v is not None:
            return v, None
        tok = uuid.uuid4().hex
        if self.r.set(f"lease:{key}", tok, nx=True, ex=self.ttl):
            return None, tok
        return None, "WAIT"

    def fill(self, key, value, token, ex=None):
        if self.r.get(f"lease:{key}") != token:
            return False
        self.r.set(key, value, ex=ex)
        self.r.delete(f"lease:{key}")
        return True

    def invalidate(self, key):
        self.r.delete(key)
        self.r.delete(f"lease:{key}")
