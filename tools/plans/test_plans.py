import unittest
import plans as P


class PlansTest(unittest.TestCase):
    cat = P.load()

    def test_quote_basic_and_commit(self):
        self.assertEqual(P.quote(self.cat, "m-4")["monthly"], 60)
        q = P.quote(self.cat, "m-4", replicas=1, years=1)
        self.assertEqual(q["monthly"], 96.0)
        self.assertEqual(q["total"], 1152.0)
        self.assertEqual(P.quote(self.cat, "s-1", years=3)["monthly"], 9.0)

    def test_free(self):
        self.assertEqual(P.quote(self.cat, "free")["total"], 0)
        with self.assertRaises(ValueError):
            P.quote(self.cat, "free", replicas=1)
        self.assertTrue(P.free_tier_allows(self.cat, 10, 1))
        self.assertFalse(P.free_tier_allows(self.cat, 500000, 1))

    def test_errors_and_fit(self):
        with self.assertRaises(KeyError):
            P.quote(self.cat, "zzz")
        with self.assertRaises(ValueError):
            P.quote(self.cat, "m-4", years=2)
        self.assertEqual(P.fit(self.cat, 3000), "m-4")
        self.assertIsNone(P.fit(self.cat, 10 ** 6))

    def test_sizes_increase(self):
        prices = [s["price_month"] for s in sorted(self.cat["sizes"], key=lambda s: s["memory_mb"])]
        self.assertEqual(prices, sorted(prices))


if __name__ == "__main__":
    unittest.main()
