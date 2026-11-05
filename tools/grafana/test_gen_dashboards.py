import json
import os
import re
import unittest
import gen_dashboards as g

ROOT = os.path.join(os.path.dirname(__file__), "../..")
OTLP_METRICS = ["cmo.clients.connected", "cmo.commands", "cmo.connections.rejected", "cmo.keys.evicted",
                "cmo.keys.expired", "cmo.keyspace.hits", "cmo.keyspace.misses", "cmo.memory.fragmentation",
                "cmo.memory.max", "cmo.memory.used", "cmo.ops.rate", "cmo.replicas.connected"]


class T(unittest.TestCase):
    def test_every_metric_charted(self):
        exprs = " ".join(p["targets"][0]["expr"] for d in g.build().values() for p in d["panels"])
        for m in OTLP_METRICS:
            self.assertIn(m.replace(".", "_"), exprs, m)

    def test_panels_valid(self):
        for d in g.build().values():
            ids = [p["id"] for p in d["panels"]]
            self.assertEqual(len(ids), len(set(ids)))
            for p in d["panels"]:
                self.assertEqual(p["datasource"]["uid"], "cmo-prom")
                e = p["targets"][0]["expr"]
                self.assertEqual(e.count("("), e.count(")"), e)

    def test_committed_files_match(self):
        for name, d in g.build().items():
            with open(os.path.join(ROOT, "deploy/grafana/dashboards", name)) as f:
                self.assertEqual(json.load(f), d, f"regenerate {name}")

    def test_provisioning_points_at_files(self):
        ds = open(os.path.join(ROOT, "deploy/grafana/provisioning/datasources/cmo.yaml")).read()
        self.assertIn("uid: cmo-prom", ds)
        db = open(os.path.join(ROOT, "deploy/grafana/provisioning/dashboards/cmo.yaml")).read()
        self.assertTrue(re.search(r"path: /var/lib/grafana/dashboards/cmo", db))


if __name__ == "__main__":
    unittest.main()
