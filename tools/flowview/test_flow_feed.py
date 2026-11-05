import json
import os
import re
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
import flow_feed as ff

HERE = os.path.dirname(os.path.abspath(__file__))


class T(unittest.TestCase):
    def test_rates(self):
        p = {"keyspace_hits": 100, "keyspace_misses": 10, "near_cache_hits": 0}
        c = {"keyspace_hits": 160, "keyspace_misses": 30, "near_cache_hits": 20}
        f = ff.flow(p, c, 2.0)
        self.assertEqual((f["req"], f["near_hit"], f["cache_hit"], f["miss"], f["db"]), (50, 10, 30, 10, 10))
        self.assertEqual(f["hit_ratio"], 0.8)

    def test_counter_reset_and_idle(self):
        f = ff.flow({"keyspace_hits": 500}, {"keyspace_hits": 3}, 1)
        self.assertEqual(f["req"], 0); self.assertIsNone(f["hit_ratio"])

    def test_assets_self_contained(self):
        for fn in ("flow.html", "flow.js"):
            src = open(os.path.join(HERE, fn)).read()
            self.assertNotRegex(src, r"https?://(?!www\.w3\.org/2000/svg)")
        html = open(os.path.join(HERE, "flow.html")).read()
        self.assertNotIn("<script>", html)  # CSP script-src 'self'
        for pid in ("p-req", "p-near", "p-hit", "p-miss", "p-db"):
            self.assertIn('id="%s"' % pid, html)

    def test_server_demo(self):
        s = ThreadingHTTPServer(("127.0.0.1", 0), ff.make_handler(ff.Source(None)))
        threading.Thread(target=s.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % s.server_port
        try:
            with urllib.request.urlopen(base + "/v1/flow") as r:
                d = json.load(r); self.assertIn("Content-Security-Policy", r.headers)
            self.assertGreater(d["req"], 0)
            with urllib.request.urlopen(base + "/") as r:
                self.assertIn(b"live data flow", r.read())
        finally:
            s.shutdown(); s.server_close()


if __name__ == "__main__":
    unittest.main()
