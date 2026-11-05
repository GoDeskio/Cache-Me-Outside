import unittest
import tiers as t


class T(unittest.TestCase):
    def test_tiered(self):
        c = t.TieredCache({"a": 1})
        self.assertEqual(c.read("a"), (1, "db")); self.assertEqual(c.read("a"), (1, "follower"))
        self.assertEqual(c.read("a", 1), (1, "leader"))
        c.write("a", 2); self.assertEqual(c.read("a"), (2, "leader")); self.assertEqual(c.read("a", 1)[0], 2)

    def test_versions_gc(self):
        r = t.VersionedRow({"cf": {"max_versions": 2, "max_age": 100}})
        for ts in (10, 50, 90): r.put("cf", "c", ts, ts)
        self.assertEqual(r.get("cf", "c"), [(90, 90)]); self.assertEqual(r.get("cf", "c", at=60), [(50, 50)])
        r.gc(now=140); self.assertEqual(r.get("cf", "c", versions=9), [(90, 90), (50, 50)])
        r.gc(now=170); self.assertEqual(r.get("cf", "c", versions=9), [(90, 90)])
        with self.assertRaises(KeyError): r.put("nope", "c", 1, 1)

    def test_splits_locality(self):
        a = t.plan_splits([("a", 500), ("m", 10), ("p", 20), ("z", 50)], 100, 30)
        self.assertEqual(a, [("split", "a"), ("merge", "m", "p")])
        self.assertEqual(t.locality_tier({"x": 90, "y": 9, "z": 1}), {"x": "hot", "y": "cold", "z": "cold"})


if __name__ == "__main__":
    unittest.main()
