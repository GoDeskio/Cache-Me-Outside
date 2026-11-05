import random
import unittest
import evict_sim as e


class T(unittest.TestCase):
    def test_lru_basic(self):
        c = e.LRU(2)
        self.assertEqual([c.access(k) for k in "abacb"], [False, False, True, False, False])

    def test_tinylfu_resists_scan(self):
        rnd = random.Random(1)
        hot = [str(rnd.randint(0, 49)) for _ in range(3000)]
        trace = []
        for i, k in enumerate(hot):
            trace.append(k)
            if i % 2: trace.append("scan%d" % i)  # one-hit wonders
        r = e.replay(trace, 50)
        self.assertGreater(r["tinylfu"]["hit_ratio"], r["lru"]["hit_ratio"])
        self.assertEqual(e.recommend(r)[0], max(r, key=lambda n: r[n]["hit_ratio"]))

    def test_2q_capacity_and_presets(self):
        c = e.TwoQ(8)
        for i in range(100): c.access(i % 13)
        self.assertLessEqual(len(c.a1in) + len(c.am), 8)
        for p in e.PRESETS.values(): self.assertIn("maxmemory-policy", p)
        self.assertEqual(e.replay([], 4)["lru"]["hit_ratio"], 0.0)


if __name__ == "__main__":
    unittest.main()
