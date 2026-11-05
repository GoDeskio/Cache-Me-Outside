#!/usr/bin/env python3
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pricing


class PricingTest(unittest.TestCase):
    def test_default_is_flat_and_placeholder(self):
        cat = pricing.load()
        self.assertEqual(cat["default_mode"], "flat")
        for plan in cat["plans"].values():
            self.assertEqual(plan["price_month"], "PLACEHOLDER")
        self.assertEqual(cat["gb_hour"], "PLACEHOLDER")
        with self.assertRaises(ValueError):
            pricing.quote(cat, "m-4")
        with self.assertRaises(ValueError):
            pricing.quote(cat, "m-4", "gb_hour")

    def test_numeric_flat_and_optional_gb_hour(self):
        cat = {
            "default_mode": "flat",
            "gb_hour": "PLACEHOLDER",
            "plans": {"s-1": {"price_month": 15, "gb_hour": 2}},
        }
        self.assertEqual(pricing.quote(cat, "s-1"), 15)
        self.assertEqual(pricing.quote(cat, "s-1", "gb_hour"), 2)
        # A plan can omit its own gb_hour and use the catalog rate.
        cat["plans"]["free"] = {"price_month": 0}
        cat["gb_hour"] = 1
        self.assertEqual(pricing.quote(cat, "free", "gb_hour"), 1)


if __name__ == "__main__":
    unittest.main()
