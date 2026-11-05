import json, os, sys, unittest
HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
import build_dashboard as b
ROOT = os.path.join(HERE, "..", "..")


class T(unittest.TestCase):
    def test_checked_in_file_is_current(self):
        with open(os.path.join(ROOT, "deploy/helm/cache-me-outside/dashboards/cmo-overview.json")) as f:
            self.assertEqual(json.load(f), b.build(), "rerun build_dashboard.py")

    def test_unique_ids_and_no_overlap(self):
        d = b.build()
        ids = [p["id"] for p in d["panels"]]
        self.assertEqual(len(ids), len(set(ids)))
        cells = set()
        for p in d["panels"]:
            g = p["gridPos"]
            self.assertLessEqual(g["x"] + g["w"], 24)
            for x in range(g["x"], g["x"] + g["w"]):
                for y in range(g["y"], g["y"] + g["h"]):
                    self.assertNotIn((x, y), cells, p["title"])
                    cells.add((x, y))

    def test_queries_balanced_and_filtered(self):
        for p in b.build()["panels"]:
            for t in p["targets"]:
                e = t["expr"]
                self.assertEqual(e.count("("), e.count(")"), e)
                self.assertEqual(e.count("{"), e.count("}"), e)
                self.assertIn('instance=~"$instance"', e, p["title"])

    def test_no_hardcoded_datasource(self):
        s = json.dumps(b.build())
        self.assertNotIn('"uid": "prometheus"', s)


if __name__ == "__main__":
    unittest.main()
