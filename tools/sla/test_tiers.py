#!/usr/bin/env python3
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tiers


class SlaTest(unittest.TestCase):
    def test_only_two_tiers(self):
        self.assertEqual(tiers.names(), ["99.9", "99.95"])
        self.assertNotIn("99.99", tiers.names())
        self.assertNotIn("99.999", tiers.names())

    def test_downtime_budget(self):
        # 0.1% of 30 days is 43.2 minutes.
        self.assertEqual(tiers.downtime_minutes("99.9"), 43.2)
        self.assertEqual(tiers.downtime_minutes("99.95"), 21.6)


if __name__ == "__main__":
    unittest.main()
