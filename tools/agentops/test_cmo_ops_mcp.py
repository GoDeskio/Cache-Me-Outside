import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from cmo_ops_mcp import Server, Api

DBS = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, st, obj):
        b = json.dumps(obj).encode()
        self.send_response(st); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _auth(self):
        if self.headers.get("Authorization") != "Bearer t0k":
            self._send(401, {"error": "unauthorized"}); return False
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._auth(): return
        if self.path == "/v1/databases": return self._send(200, {"databases": sorted(DBS)})
        n = self.path.rsplit("/", 1)[1]
        self._send(200, DBS[n]) if n in DBS else self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth(): return
        b = self._body()
        if self.path == "/v1/databases":
            DBS[b["name"]] = b; return self._send(201, {**b, "password": "once"})
        self._send(200, {"password": "new"})

    def do_PATCH(self):
        if not self._auth(): return
        n = self.path.rsplit("/", 1)[1]; DBS[n].update(self._body()); self._send(200, DBS[n])

    def do_DELETE(self):
        if not self._auth(): return
        DBS.pop(self.path.rsplit("/", 1)[1], None); self._send(200, {"deleted": True})


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.server_port

    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()

    def call(self, s, name, args):
        return s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]

    def test_full_lifecycle(self):
        audit = os.path.join(tempfile.mkdtemp(), "a.jsonl")
        s = Server(Api(self.base, "t0k"), audit)
        self.assertFalse(self.call(s, "db_create", {"name": "acme", "ops_per_sec": 100}).get("isError"))
        self.call(s, "db_set_limits", {"name": "acme", "ops_per_sec": 500})
        self.assertEqual(DBS["acme"]["ops_per_sec"], 500)
        r = self.call(s, "db_delete", {"name": "acme", "confirm": "nope"})
        self.assertTrue(r["isError"]); self.assertIn("acme", DBS)
        self.call(s, "db_rotate_password", {"name": "acme", "confirm": "acme"})
        self.call(s, "db_delete", {"name": "acme", "confirm": "acme"})
        self.assertNotIn("acme", DBS)
        log = [json.loads(l) for l in open(audit)]
        self.assertEqual([e["tool"] for e in log], ["db_create", "db_set_limits", "db_rotate_password", "db_delete"])
        self.assertNotIn("t0k", open(audit).read())

    def test_errors_and_protocol(self):
        s = Server(Api(self.base, "bad"))
        self.assertTrue(self.call(s, "db_list", {})["isError"])
        self.assertTrue(self.call(s, "rm_rf", {})["isError"])
        self.assertTrue(self.call(Server(Api(self.base, "t0k")), "db_set_limits", {"name": "x"})["isError"])
        tl = s.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual(len(tl), 6)
        self.assertIn("error", s.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"}))
        self.assertIsNone(s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))


if __name__ == "__main__":
    unittest.main()
