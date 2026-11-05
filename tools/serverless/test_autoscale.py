import unittest
from autoscale import Autoscaler


class T(unittest.TestCase):
    def test_scale_out_proportional_and_capped(self):
        a = Autoscaler()
        self.assertEqual(a.decide(4, 0.95, 0.5, 0), 6)
        self.assertEqual(Autoscaler(max_nodes=5).decide(4, 1.0, 1.0, 0), 5)

    def test_cooldown(self):
        a = Autoscaler()
        a.decide(4, 0.95, 0.5, 0)
        self.assertEqual(a.decide(6, 0.95, 0.5, 100), 6)
        self.assertGreater(a.decide(6, 0.95, 0.5, 400), 6)

    def test_scale_in_slow_and_safe(self):
        a = Autoscaler()
        self.assertEqual(a.decide(6, 0.1, 0.2, 0), 6)
        self.assertEqual(a.decide(6, 0.1, 0.2, 10), 6)
        self.assertEqual(a.decide(6, 0.1, 0.2, 20), 5)
        b = Autoscaler(scale_in_after=1)
        self.assertEqual(b.decide(3, 0.0, 0.0, 0), 3)  # min floor

    def test_steady(self):
        self.assertEqual(Autoscaler().decide(5, 0.5, 0.5, 0), 5)


if __name__ == "__main__":
    unittest.main()
