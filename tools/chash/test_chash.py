import unittest
from chash import Ring


class T(unittest.TestCase):
    def test_stable_and_weighted(self):
        r = Ring({"a": 1, "b": 1, "c": 2})
        keys = [f"k{i}" for i in range(20000)]
        counts = {}
        for k in keys:
            counts[r.lookup(k)] = counts.get(r.lookup(k), 0) + 1
        self.assertGreater(counts["c"], counts["a"] * 1.5)
        self.assertEqual(r.lookup("x"), Ring({"a": 1, "b": 1, "c": 2}).lookup("x"))

    def test_minimal_movement(self):
        keys = [f"k{i}" for i in range(5000)]
        r1, r2 = Ring({"a": 1, "b": 1, "c": 1}), Ring({"a": 1, "b": 1, "c": 1, "d": 1})
        moved = [k for k in keys if r1.lookup(k) != r2.lookup(k)]
        self.assertTrue(all(r2.lookup(k) == "d" for k in moved))
        self.assertLess(len(moved), len(keys) * 0.4)

    def test_lookup_n_distinct(self):
        r = Ring({"a": 1, "b": 1})
        self.assertEqual(sorted(r.lookup_n("z", 5)), ["a", "b"])

    def test_errors(self):
        with self.assertRaises(ValueError):
            Ring({})
        with self.assertRaises(ValueError):
            Ring({"a": 0})


if __name__ == "__main__":
    unittest.main()
