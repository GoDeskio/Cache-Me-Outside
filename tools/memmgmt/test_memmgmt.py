import unittest
import memmgmt as m


class T(unittest.TestCase):
    def test_rebalance(self):
        p = {"a": {"bytes": 100, "marginal_hits": 1}, "b": {"bytes": 100, "marginal_hits": 50}}
        self.assertEqual(m.rebalance(p, 10), {"from": "a", "to": "b", "bytes": 10})
        p["a"]["min"] = 90
        self.assertIsNone(m.rebalance(p, 10))

    def test_admission(self):
        t = [0.0]
        a = m.WriteBudgetAdmission(100, clock=lambda: t[0])
        self.assertTrue(a.admit(80)); self.assertFalse(a.admit(80)); self.assertTrue(a.admit(80, hits=3))
        t[0] = 1.0; self.assertTrue(a.admit(90))

    def test_sized_cache(self):
        c = m.SizedCache(10, sizeof=len)
        c.put("a", "xxxx"); c.put("b", "xxxx"); c.get("a"); c.put("c", "xxxx")
        self.assertIsNone(c.get("b")); self.assertEqual(c.get("a"), "xxxx")
        self.assertFalse(c.put("big", "x" * 11)); self.assertLessEqual(c.used, 10)

    def test_reaper_and_monitor(self):
        self.assertEqual(m.reaper_preset(0.9, 0)["active-expire-effort"], 7)
        self.assertEqual(m.reaper_preset(0.1, 0.0)["hz"], 10)
        mm = m.MemoryMonitor(window=2)
        self.assertEqual(mm.observe(90, 100), "hold"); self.assertEqual(mm.observe(95, 100), "scale-up")
        mm.observe(10, 100); self.assertEqual(mm.observe(10, 100), "scale-down")


if __name__ == "__main__":
    unittest.main()
