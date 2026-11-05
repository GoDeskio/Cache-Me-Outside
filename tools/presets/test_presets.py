import unittest
import presets as P


class T(unittest.TestCase):
    def test_io(self):
        self.assertEqual(P.io(1), ["io-threads 1"])
        self.assertEqual(P.io(4), ["io-threads 3"])
        self.assertEqual(P.io(64), ["io-threads 8"])
        with self.assertRaises(ValueError):
            P.io(0)

    def test_render_combo(self):
        s = P.render(["io", "strong"], cores=4, replicas=2)
        self.assertIn("min-replicas-to-write 2", s)
        self.assertIn("appendfsync always", s)
        self.assertIn("io-threads 3", s)

    def test_cache(self):
        s = P.render(["cache"])
        self.assertIn("maxmemory-policy allkeys-lfu", s)
        self.assertIn('save ""', s)

    def test_refusals(self):
        for bad in (["cache", "strong"], ["nope"]):
            with self.assertRaises(ValueError):
                P.render(bad)
        with self.assertRaises(ValueError):
            P.strong(0)
        with self.assertRaises(ValueError):
            P.render(["io", "io"], cores=2)

    def test_rdma(self):
        self.assertIn("rdma-port 6379", P.render(["rdma"]))


if __name__ == "__main__":
    unittest.main()
