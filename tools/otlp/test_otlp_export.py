import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
import otlp_export as O

INFO = "# Server\r\nrole:master\r\nused_memory:1000\r\nkeyspace_hits:30\r\nkeyspace_misses:10\r\nconnected_clients:4\r\nmem_fragmentation_ratio:1.5\r\nfoo:bar\r\n"


class Sink(BaseHTTPRequestHandler):
    got = []

    def do_POST(self):
        Sink.got.append((self.path, self.headers.get("x-key"), json.loads(self.rfile.read(int(self.headers["content-length"])))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class T(unittest.TestCase):
    def test_parse_and_convert(self):
        info = O.parse_info(INFO)
        self.assertEqual(info["role"], "master")
        body = O.to_otlp({"n1": info}, 2, 1)
        ms = {m["name"]: m for m in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        self.assertEqual(ms["cmo.memory.used"]["gauge"]["dataPoints"][0]["asDouble"], 1000)
        self.assertTrue(ms["cmo.keyspace.hits"]["sum"]["isMonotonic"])
        self.assertEqual(ms["cmo.keyspace.hits"]["sum"]["dataPoints"][0]["startTimeUnixNano"], "1")
        self.assertAlmostEqual(ms["cmo.keyspace.hit_ratio"]["gauge"]["dataPoints"][0]["asDouble"], 0.75)
        self.assertNotIn("cmo.keys.evicted", ms)

    def test_push(self):
        s = HTTPServer(("127.0.0.1", 0), Sink)
        threading.Thread(target=s.handle_request, daemon=True).start()
        st = O.push("http://127.0.0.1:%d/" % s.server_address[1], {"a": 1}, {"x-key": "k"})
        self.assertEqual(st, 200)
        self.assertEqual(Sink.got[-1], ("/v1/metrics", "k", {"a": 1}))
        s.server_close()


if __name__ == "__main__":
    unittest.main()
