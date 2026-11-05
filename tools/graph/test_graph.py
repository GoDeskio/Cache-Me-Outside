import unittest
from graph import Graph, Leases


class FakeRedis:
    def __init__(self): self.kv, self.h, self.z = {}, {}, {}
    def hset(self, k, mapping): self.h.setdefault(k, {}).update(mapping)
    def hgetall(self, k): return dict(self.h.get(k, {}))
    def delete(self, k): self.kv.pop(k, None); self.h.pop(k, None); self.z.pop(k, None)
    def incr(self, k): self.kv[k] = int(self.kv.get(k, 0)) + 1; return self.kv[k]
    def get(self, k): return self.kv.get(k)
    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv: return None
        self.kv[k] = v; return True
    def zadd(self, k, m): self.z.setdefault(k, {}).update(m)
    def zrem(self, k, m): self.z.get(k, {}).pop(m, None)
    def zcard(self, k): return len(self.z.get(k, {}))
    def zrevrangebyscore(self, k, hi, lo, start=0, num=None):
        hi = float("inf") if hi == "+inf" else hi; lo = float("-inf") if lo == "-inf" else lo
        items = sorted(((s, m) for m, s in self.z.get(k, {}).items() if lo <= s <= hi), reverse=True)
        return [m for _, m in items[start:start + num]]


class T(unittest.TestCase):
    def test_objects(self):
        g = Graph(FakeRedis())
        u = g.obj_add("user", {"n": "a"})
        self.assertEqual(g.obj_get(u)["data"], {"n": "a"})
        v = g.obj_update(u, {"n": "b"})
        self.assertTrue(g.fresh_enough(u, v)); self.assertFalse(g.fresh_enough(u, v + 1))
        g.obj_delete(u)
        self.assertIsNone(g.obj_get(u))

    def test_assocs(self):
        g = Graph(FakeRedis())
        for i in range(5):
            g.assoc_add("u1", "friend", f"u{i+2}", t=i, inverse="friend")
        self.assertEqual(g.assoc_range("u1", "friend", 0, 2), ["u6", "u5"])
        self.assertEqual(g.assoc_time_range("u1", "friend", 3, 1), ["u5", "u4", "u3"])
        self.assertEqual(g.assoc_count("u3", "friend"), 1)
        g.assoc_delete("u1", "friend", "u6", inverse="friend")
        self.assertEqual((g.assoc_count("u1", "friend"), g.assoc_count("u6", "friend")), (4, 0))

    def test_leases(self):
        L = Leases(FakeRedis())
        v, tok = L.get("k")
        self.assertIsNone(v)
        self.assertEqual(L.get("k"), (None, "WAIT"))
        L.invalidate("k")
        self.assertFalse(L.fill("k", "stale", tok))
        _, tok2 = L.get("k")
        self.assertTrue(L.fill("k", "fresh", tok2))
        self.assertEqual(L.get("k"), ("fresh", None))


if __name__ == "__main__":
    unittest.main()
