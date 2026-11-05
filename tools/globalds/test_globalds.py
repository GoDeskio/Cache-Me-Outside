import unittest
import globalds as G

RTT = {"eu": {"eu": 5, "us": 90, "ap": 200}, "ap": {"ap": 5, "us": 120, "eu": 200}}


class T(unittest.TestCase):
    def setUp(self):
        self.r = G.Router("us", RTT)
        for reg in ("us", "eu", "ap"):
            self.r.report(reg, True, 0.1)

    def test_reads_nearest_writes_primary(self):
        self.assertEqual(self.r.pick("eu"), "eu")
        self.assertEqual(self.r.pick("eu", write=True), "us")
        self.assertEqual(self.r.pick("unknown"), "us")

    def test_lag_and_health_fallback(self):
        self.r.report("eu", True, 10)
        self.assertEqual(self.r.pick("eu"), "us")
        self.r.report("ap", False)
        self.assertEqual(self.r.pick("ap"), "us")

    def test_promote(self):
        self.r.report("us", False)
        self.r.report("ap", True, 0.5)
        new, cmds = G.promote(self.r)
        self.assertEqual(new, "eu")
        self.assertEqual(cmds[0], ("eu", ["REPLICAOF", "NO", "ONE"]))
        self.assertEqual(self.r.pick("eu", write=True), "eu")

    def test_config_has_no_secret(self):
        c = G.replica_config("p.example")
        self.assertIn("tls-replication yes", c)
        self.assertFalse(any(l.startswith("masterauth") for l in c))


if __name__ == "__main__":
    unittest.main()
