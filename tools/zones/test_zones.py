import unittest
from zones import ZoneClient, LatchError, Throttled, needed


class Mem:
    def __init__(self, fail=False): self.d, self.fail = {}, fail
    def _c(self):
        if self.fail: raise ConnectionError("down")
    def get(self, k): self._c(); return self.d.get(k)
    def set(self, k, v, ttl=None): self._c(); self.d[k] = v
    def delete(self, k): self._c(); self.d.pop(k, None)


class T(unittest.TestCase):
    def test_needed(self):
        self.assertEqual([needed(p, 3) for p in ("ONE", "QUORUM", "ALL_MINUS_1", "ALL")], [1, 2, 2, 3])

    def test_latch(self):
        z = {"a": Mem(), "b": Mem(), "c": Mem(True)}
        c = ZoneClient(z, "a", "QUORUM")
        self.assertEqual(c.set("k", 1)["failed"], ["c"])
        with self.assertRaises(LatchError):
            c.set("k", 1, policy="ALL")

    def test_local_then_fallback(self):
        z = {"a": Mem(), "b": Mem()}
        z["b"].d["k"] = 9
        c = ZoneClient(z, "a")
        self.assertEqual(c.get("k"), 9)
        self.assertEqual(c.stats["fallback_reads"], 1)
        z["a"].fail = True
        self.assertEqual(c.get("k"), 9)

    def test_bulk(self):
        z = {"a": Mem(), "b": Mem()}
        z["a"].d["x"] = 1; z["b"].d["y"] = 2
        c = ZoneClient(z, "a")
        self.assertEqual(c.get_bulk(["x", "y", "z"]), {"x": 1, "y": 2})
        self.assertEqual(c.stats["fallback_reads"], 1)

    def test_throttle(self):
        c = ZoneClient({"a": Mem()}, "a", max_inflight=1)
        c.sem.acquire()
        with self.assertRaises(Throttled):
            c.get("k")

    def test_bad_args(self):
        with self.assertRaises(ValueError):
            ZoneClient({"a": Mem()}, "b")
        with self.assertRaises(ValueError):
            ZoneClient({"a": Mem()}, "a", "MOST")


if __name__ == "__main__":
    unittest.main()
