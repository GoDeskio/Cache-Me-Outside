import base64
import json
import socketserver
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import cmo_rest as R


class FakeValkey(socketserver.StreamRequestHandler):
    """Tiny RESP server: AUTH app:pw, SET, GET, INCR, plus an error."""
    store = {}

    def handle(self):
        authed = False
        while True:
            line = self.rfile.readline()
            if not line:
                return
            n = int(line[1:])
            args = []
            for _ in range(n):
                ln = int(self.rfile.readline()[1:])
                args.append(self.rfile.read(ln + 2)[:-2].decode())
            cmd = args[0].upper()
            if cmd == "AUTH":
                authed = args[1:] == ["app", "pw"]
                self.wfile.write(b"+OK\r\n" if authed else b"-WRONGPASS invalid\r\n")
            elif not authed:
                self.wfile.write(b"-NOAUTH\r\n")
            elif cmd == "SET":
                self.store[args[1]] = args[2]
                self.wfile.write(b"+OK\r\n")
            elif cmd == "GET":
                v = self.store.get(args[1])
                self.wfile.write(b"$-1\r\n" if v is None else b"$%d\r\n%s\r\n" % (len(v), v.encode()))
            elif cmd == "INCR":
                v = int(self.store.get(args[1], "0")) + 1
                self.store[args[1]] = str(v)
                self.wfile.write(b":%d\r\n" % v)
            elif cmd == "MGET":
                self.wfile.write(b"*2\r\n$1\r\na\r\n$-1\r\n")
            else:
                self.wfile.write(b"-NOPERM no\r\n")


class RestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeValkey)
        threading.Thread(target=cls.v.serve_forever, daemon=True).start()
        R.Handler.upstream = "127.0.0.1:%d" % cls.v.server_address[1]
        cls.h = ThreadingHTTPServer(("127.0.0.1", 0), R.Handler)
        threading.Thread(target=cls.h.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d" % cls.h.server_address[1]
        cls.key = base64.urlsafe_b64encode(b"app:pw").decode().rstrip("=")

    @classmethod
    def tearDownClass(cls):
        cls.h.shutdown()
        cls.v.shutdown()

    def call(self, method, path, body=None, key=None):
        req = urllib.request.Request(self.base + path, method=method, data=None if body is None else json.dumps(body).encode())
        if key:
            req.add_header("authorization", "Bearer " + key)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_set_get(self):
        self.assertEqual(self.call("POST", "/", ["SET", "k", "v"], self.key), (200, {"result": "OK"}))
        self.assertEqual(self.call("GET", "/GET/k", key=self.key), (200, {"result": "v"}))

    def test_pipeline(self):
        s, out = self.call("POST", "/pipeline", [["INCR", "n"], ["INCR", "n"], ["MGET", "a", "b"]], self.key)
        self.assertEqual(s, 200)
        self.assertEqual(out[1], {"result": 2})
        self.assertEqual(out[2], {"result": ["a", None]})

    def test_auth(self):
        self.assertEqual(self.call("GET", "/GET/k")[0], 401)
        bad = base64.urlsafe_b64encode(b"app:nope").decode()
        self.assertEqual(self.call("GET", "/GET/k", key=bad)[0], 401)

    def test_blocked_and_acl_errors(self):
        self.assertEqual(self.call("POST", "/", ["SUBSCRIBE", "c"], self.key)[0], 400)
        self.assertEqual(self.call("POST", "/", ["XREAD", "BLOCK", "0", "STREAMS", "s", "$"], self.key)[0], 400)
        s, out = self.call("POST", "/", ["FLUSHALL"], self.key)
        self.assertEqual(s, 400)
        self.assertIn("NOPERM", out["error"])
        self.assertEqual(self.call("POST", "/", [], self.key)[0], 400)

    def test_health(self):
        self.assertEqual(self.call("GET", "/health"), (200, {"ok": True}))


if __name__ == "__main__":
    unittest.main()
