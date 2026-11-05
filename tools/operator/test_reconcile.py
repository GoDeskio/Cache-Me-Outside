import unittest
from reconcile import reconcile

SPEC = {"shards": 2, "replicas": 1, "version": "9.0"}


def pod(n, s, role, v="9.0", ready=True):
    return {"name": n, "shard": s, "role": role, "version": v, "ready": ready}


def cluster(v="9.0"):
    return [pod("s0p", 0, "primary", v), pod("s0r", 0, "replica", v),
            pod("s1p", 1, "primary", v), pod("s1r", 1, "replica", v)]


class T(unittest.TestCase):
    def test_converged(self):
        self.assertEqual(reconcile(SPEC, {"pods": cluster()}), [])

    def test_wait_and_promote(self):
        p = cluster(); p[3]["ready"] = False
        self.assertEqual(reconcile(SPEC, {"pods": p})[0][0], "wait")
        p = cluster()[1:]
        self.assertEqual(reconcile(SPEC, {"pods": p}), [("promote", "s0r")])

    def test_scale(self):
        self.assertEqual(reconcile(dict(SPEC, shards=3), {"pods": cluster()}),
                         [("create_shard", 2), ("rebalance", 3)])
        self.assertEqual(reconcile(dict(SPEC, shards=1), {"pods": cluster()}),
                         [("rebalance", 1), ("delete_shard", 1)])
        self.assertEqual(reconcile(dict(SPEC, replicas=2), {"pods": cluster()}),
                         [("add_replica", 0), ("add_replica", 1)])

    def test_rolling_upgrade_replica_first(self):
        self.assertEqual(reconcile(dict(SPEC, version="9.1"), {"pods": cluster()}), [("upgrade", "s0r")])
        p = cluster(); p[1]["version"] = "9.1"
        self.assertEqual(reconcile(dict(SPEC, version="9.1"), {"pods": p}), [("failover", "s0p")])


if __name__ == "__main__":
    unittest.main()
