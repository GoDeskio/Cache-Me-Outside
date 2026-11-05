import unittest
import timeread as t


class T(unittest.TestCase):
    def test_hlc(self):
        clk = [1000]; slept = []
        def sl(s): slept.append(s); clk[0] += int(s * 1000) + 1
        h = t.HLC(5, clock=lambda: clk[0], sleep=sl)
        a = h.now(); b = h.now(); self.assertLess(a, b)
        self.assertEqual(h.update((2000, 3)), (2000, 4))
        h.commit_wait((1000, 0)); self.assertTrue(slept); self.assertGreater(h.interval()[0], 1000)

    def test_pick_replica(self):
        rs = [{"name": "far", "applied_ms": 990}, {"name": "near", "applied_ms": 950, "local": True}]
        self.assertEqual(t.pick_replica(rs, max_staleness_ms=100, now_ms=1000), "near")
        self.assertEqual(t.pick_replica(rs, max_staleness_ms=20, now_ms=1000), "far")
        self.assertIsNone(t.pick_replica(rs, at_ms=995, now_ms=1000))

    def test_mv_and_placement(self):
        s = t.MVStore(); s.write("a", 10, "x"); s.write("a", 20, "y"); s.write("b", 15, "z")
        self.assertEqual(s.snapshot(12, ["a", "b"]), {"a": "x", "b": None}); self.assertEqual(s.read("a", 99), "y")
        p = t.Placement({"eu:": "eu-west", "eu:de:": "eu-central"}, "us-east")
        self.assertEqual(p.region("eu:de:1"), "eu-central"); self.assertEqual(p.region("x"), "us-east")
        self.assertEqual(p.plan({"eu:1": "us-east", "x": "us-east"}), {"eu:1": "eu-west"})


if __name__ == "__main__":
    unittest.main()
