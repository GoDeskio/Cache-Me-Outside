import time
import unittest
from routes import Failover, MissFailover, Shadow, WarmUp, Replicated, Prefix, Mem, RouteError


class T(unittest.TestCase):
    def test_failover(self):
        a, b = Mem(fail=True), Mem()
        f = Failover([a, b])
        f.set("k", 1)
        self.assertEqual(b.d["k"], 1)
        with self.assertRaises(RouteError):
            Failover([Mem(True)]).get("k")

    def test_miss_failover(self):
        a, b = Mem(), Mem()
        b.d["k"] = 2
        self.assertEqual(MissFailover([a, b]).get("k"), 2)

    def test_shadow_swallow(self):
        p = Mem()
        s = Shadow(p, Mem(fail=True))
        s.set("k", 3)
        self.assertEqual(s.get("k"), 3)

    def test_warmup_backfills(self):
        cold, warm = Mem(), Mem()
        warm.d["k"] = 4
        w = WarmUp(cold, warm)
        self.assertEqual(w.get("k"), 4)
        self.assertEqual(cold.d["k"], 4)
        w.delete("k")
        self.assertNotIn("k", warm.d)

    def test_replicated_modes(self):
        ok, bad = Mem(), Mem(fail=True)
        Replicated([ok, Mem(), bad], "majority").set("k", 1)
        with self.assertRaises(RouteError):
            Replicated([ok, bad], "all_sync").set("k", 1)
        self.assertTrue(Replicated([ok, bad], "initial").set("k", 2))
        a = Mem()
        Replicated([a], "all_async").set("x", 1)
        time.sleep(0.05)
        self.assertEqual(a.d["x"], 1)
        with self.assertRaises(ValueError):
            Replicated([a], "nope")

    def test_prefix(self):
        a, b, d = Mem(), Mem(), Mem()
        p = Prefix({"user:": a, "user:vip:": b}, d)
        p.set("user:vip:1", 1); p.set("user:2", 2); p.set("x", 3)
        self.assertEqual((list(b.d), list(a.d), list(d.d)), (["user:vip:1"], ["user:2"], ["x"]))


if __name__ == "__main__":
    unittest.main()
