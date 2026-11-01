"""Composable cache routes (plan #89-#93). Independent rebuild; stdlib only.

A "handle" is any object with get(key), set(key, value, ttl=None), delete(key).
Routes are handles too, so they nest.
"""
import threading


class RouteError(Exception):
    pass


class Failover:
    """#89: try each child in order on error."""
    def __init__(self, children):
        self.children = list(children)

    def _try(self, op, *a, **kw):
        last = None
        for c in self.children:
            try:
                return getattr(c, op)(*a, **kw)
            except Exception as e:  # noqa: BLE001 - failover on any backend error
                last = e
        raise RouteError(f"all children failed: {last}")

    def get(self, k): return self._try("get", k)
    def set(self, k, v, ttl=None): return self._try("set", k, v, ttl=ttl)
    def delete(self, k): return self._try("delete", k)


class MissFailover(Failover):
    """#89: on a miss (None) or error, ask the next child."""
    def get(self, k):
        for c in self.children:
            try:
                v = c.get(k)
            except Exception:  # noqa: BLE001
                continue
            if v is not None:
                return v
        return None


class Shadow:
    """#90: serve from primary; mirror a sampled share of traffic to shadow; shadow errors are swallowed."""
    def __init__(self, primary, shadow, sample=lambda key: True):
        self.p, self.s, self.sample = primary, shadow, sample

    def _mirror(self, op, k, *a, **kw):
        if self.sample(k):
            try:
                getattr(self.s, op)(k, *a, **kw)
            except Exception:  # noqa: BLE001
                pass

    def get(self, k):
        self._mirror("get", k)
        return self.p.get(k)

    def set(self, k, v, ttl=None):
        self._mirror("set", k, v, ttl=ttl)
        return self.p.set(k, v, ttl=ttl)

    def delete(self, k):
        self._mirror("delete", k)
        return self.p.delete(k)


class WarmUp:
    """#91: read cold; on miss read warm and backfill cold. Writes go to cold; deletes to both."""
    def __init__(self, cold, warm, backfill_ttl=None):
        self.cold, self.warm, self.ttl = cold, warm, backfill_ttl

    def get(self, k):
        v = self.cold.get(k)
        if v is None:
            v = self.warm.get(k)
            if v is not None:
                self.cold.set(k, v, ttl=self.ttl)
        return v

    def set(self, k, v, ttl=None): return self.cold.set(k, v, ttl=ttl)

    def delete(self, k):
        self.warm.delete(k)
        return self.cold.delete(k)


class Replicated:
    """#92: write to all children. mode: all_sync | majority | initial | all_async."""
    MODES = ("all_sync", "majority", "initial", "all_async")

    def __init__(self, children, mode="all_sync"):
        if mode not in self.MODES:
            raise ValueError(mode)
        self.children, self.mode = list(children), mode

    def _fan(self, op, *a, **kw):
        if self.mode == "all_async":
            for c in self.children:
                threading.Thread(target=lambda c=c: _quiet(getattr(c, op), *a, **kw), daemon=True).start()
            return True
        if self.mode == "initial":
            res = getattr(self.children[0], op)(*a, **kw)
            for c in self.children[1:]:
                _quiet(getattr(c, op), *a, **kw)
            return res
        ok = sum(1 for c in self.children if _quiet(getattr(c, op), *a, **kw) is not _FAIL)
        need = len(self.children) if self.mode == "all_sync" else len(self.children) // 2 + 1
        if ok < need:
            raise RouteError(f"{self.mode}: {ok}/{len(self.children)} succeeded")
        return True

    def get(self, k): return Failover(self.children).get(k)
    def set(self, k, v, ttl=None): return self._fan("set", k, v, ttl=ttl)
    def delete(self, k): return self._fan("delete", k)


class Prefix:
    """#93: route by longest matching key prefix, else default."""
    def __init__(self, table, default):
        self.table = sorted(table.items(), key=lambda kv: -len(kv[0]))
        self.default = default

    def pick(self, k):
        for p, h in self.table:
            if k.startswith(p):
                return h
        return self.default

    def get(self, k): return self.pick(k).get(k)
    def set(self, k, v, ttl=None): return self.pick(k).set(k, v, ttl=ttl)
    def delete(self, k): return self.pick(k).delete(k)


_FAIL = object()


def _quiet(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:  # noqa: BLE001
        return _FAIL


class Mem:
    """In-memory handle for tests and local dev."""
    def __init__(self, fail=False):
        self.d, self.fail = {}, fail

    def _chk(self):
        if self.fail:
            raise ConnectionError("down")

    def get(self, k):
        self._chk()
        return self.d.get(k)

    def set(self, k, v, ttl=None):
        self._chk()
        self.d[k] = v
        return True

    def delete(self, k):
        self._chk()
        return self.d.pop(k, None) is not None
