import unittest
import topology as T

HOSTS = [{"name": "h1", "zone": "a"}, {"name": "h2", "zone": "a"},
         {"name": "h3", "zone": "b"}, {"name": "h4", "zone": "c"}]


class Tst(unittest.TestCase):
    def test_spread_zones_and_distinct_hosts(self):
        p = T.place(HOSTS, 4, 2)
        zone = {h["name"]: h["zone"] for h in HOSTS}
        for s in p["shards"]:
            hs = [s["primary"]] + s["replicas"]
            self.assertEqual(len(set(hs)), 3)
            self.assertEqual(len({zone[h] for h in hs}), 3)

    def test_too_few_hosts_or_memory(self):
        with self.assertRaises(ValueError):
            T.place(HOSTS[:1], 1, 1)
        with self.assertRaises(ValueError):
            T.place([{"name": "x", "free_mb": 100}, {"name": "y", "free_mb": 100}], 1, 1, mem_mb=200)

    def test_sla_tiers(self):
        self.assertEqual(T.sla(T.place(HOSTS, 2, 0))["tier"], "99.9")
        self.assertEqual(T.sla(T.place(HOSTS, 2, 1))["tier"], "99.99")
        same_zone = [{"name": "a1", "zone": "a"}, {"name": "a2", "zone": "a"}]
        self.assertEqual(T.sla(T.place(same_zone, 1, 1))["tier"], "99.95")
        multi = [{"name": n, "zone": z, "region": r} for n, z, r in
                 [("p", "a", "r1"), ("q", "b", "r1"), ("s", "c", "r2")]]
        self.assertEqual(T.sla(T.place(multi, 1, 2))["tier"], "99.999")

    def test_upgrade_replicas_first(self):
        p = T.place(HOSTS, 2, 1)
        steps = T.upgrade_order(p)
        prim = {s["primary"] for s in p["shards"]}
        kinds = [st["host"] in prim for st in steps]
        self.assertEqual(kinds, sorted(kinds))
        self.assertEqual(len(steps), 4)
        self.assertTrue(any("warning" in st for st in T.upgrade_order(T.place(HOSTS, 1, 0))))


if __name__ == "__main__":
    unittest.main()
