import random
import unittest
import observe as o


class T(unittest.TestCase):
    def test_bloom(self):
        b = o.Bloom(1000, 0.01)
        for i in range(1000): b.add(i)
        self.assertTrue(all(i in b for i in range(1000)))
        fp = sum(("x%d" % i) in b for i in range(10000))
        self.assertLess(fp, 300)

    def test_klog_redacts_and_samples(self):
        lines = ['1.5 [0 10.0.0.5:4242] "SET" "k" "secret"', '1.6 [0 10.0.0.5:4242] "AUTH" "pw"',
                 '1.7 [0 10.0.0.5:4242] "GET" "k"', 'garbage']
        out = list(o.klog(lines, every=1, rng=random.Random(0)))
        self.assertEqual(out[0]["cmd"], ["SET", "k", "<redacted>"])
        self.assertEqual(out[1]["cmd"], ["AUTH", "<redacted>"])
        self.assertEqual(out[2]["cmd"], ["GET", "k"]); self.assertEqual(len(out), 3)
        self.assertNotIn("secret", str(out))
        many = list(o.klog(lines[2:3] * 10000, every=100, rng=random.Random(1)))
        self.assertTrue(50 < len(many) < 160)

    def test_spans(self):
        t = o.Tracer()
        with t.span("cache.get", key="k"): pass
        with self.assertRaises(ValueError):
            with t.span("cache.set"): raise ValueError
        sp = t.otlp()["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual([s["status"]["code"] for s in sp], [1, 2])


if __name__ == "__main__":
    unittest.main()
