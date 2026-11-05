import os, socket, sys, threading, unittest
sys.path.insert(0, os.path.dirname(__file__))
import cmo_browse as b


def enc(v):
    if v is None: return b"$-1\r\n"
    if isinstance(v, int): return b":%d\r\n" % v
    if isinstance(v, str): return b"+%s\r\n" % v.encode()
    if isinstance(v, bytes): return b"$%d\r\n%s\r\n" % (len(v), v)
    return b"*%d\r\n" % len(v) + b"".join(enc(x) for x in v)


class Fake:
    def __init__(self, data):
        self.data, self.log = data, []
        self.a, self.s = socket.socketpair()
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        f = self.s.makefile("rb")
        while True:
            try: c = b._read(f)
            except Exception: return
            c = [x.decode() for x in c]; self.log.append(c); op, k = c[0], (c[1] if len(c) > 1 else None)
            v = self.data.get(k)
            if op == "SCAN":
                pat = c[3].rstrip("*")
                r = [b"0", [x.encode() for x in self.data if x.startswith(pat)]]
            elif op == "TYPE":
                r = "none" if v is None else {str: "string", list: "list", dict: "hash"}[type(v)]
            elif op == "TTL": r = -1
            elif op == "STRLEN": r = len(v)
            elif op == "GET": r = v.encode()
            elif op == "LLEN": r = len(v)
            elif op == "LRANGE": r = [x.encode() for x in v[: int(c[3]) + 1]]
            elif op == "HLEN": r = len(v)
            elif op == "HSCAN": r = ["0", [y.encode() for kv in v.items() for y in kv]]
            else: r = "OK"
            self.s.sendall(enc(r))


class T(unittest.TestCase):
    def setUp(self):
        self.f = Fake({"acme:s": "x" * 5000, "acme:l": [str(i) for i in range(150)],
                       "acme:h": {"a": "1"}, "other:s": "secret"})
        self.c = b.Conn(None, None, None, None, sock=self.f.a)

    def test_scan_is_scoped(self):
        r = b.scan(self.c, "acme")
        self.assertNotIn("other:s", r["keys"])
        self.assertEqual(self.f.log[-1][3], "acme:*")

    def test_cannot_read_other_db(self):
        with self.assertRaises(PermissionError):
            b.show(self.c, "acme", "other:s")

    def test_string_truncated(self):
        r = b.show(self.c, "acme", "acme:s")
        self.assertEqual(r["size"], 5000)
        self.assertTrue(r["value"].endswith("…"))

    def test_list_capped(self):
        r = b.show(self.c, "acme", "acme:l")
        self.assertEqual(len(r["value"]), 100)
        self.assertTrue(r["truncated"])

    def test_hash_and_missing(self):
        self.assertEqual(b.show(self.c, "acme", "acme:h")["value"], {"a": "1"})
        self.assertIsNone(b.show(self.c, "acme", "acme:nope"))

    def test_read_only(self):
        with self.assertRaises(PermissionError):
            self.c.cmd("DEL", "acme:s")

    def test_backslash_rejected(self):
        with self.assertRaises(ValueError):
            b.scan(self.c, "acme", pattern="\\*")

    def test_api_route(self):
        import cmo_mgmt as m, tempfile, http.server, cmoctl
        sys.path.insert(0, os.path.dirname(__file__))
        from test_cmo_mgmt import FakeAcl, TOKEN
        d = tempfile.mkdtemp()
        mgr = m.Manager(m.Store(os.path.join(d, "p.json"), "x:1"), FakeAcl())
        mgr.browser_conn = lambda: b.Conn(None, None, None, None, sock=Fake({"acme:h": {"a": "1"}}).a)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(mgr, TOKEN))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        self.assertEqual(cmoctl.call("GET", "/v1/databases/acme/keys", None, base, TOKEN)[0], 404)
        cmoctl.call("POST", "/v1/databases", {"name": "acme"}, base, TOKEN)
        st, r = cmoctl.call("GET", "/v1/databases/acme/keys?match=h*", None, base, TOKEN)
        self.assertEqual((st, r["keys"]), (200, ["acme:h"]))
        st, r = cmoctl.call("GET", "/v1/databases/acme/keys?key=acme%3Ah", None, base, TOKEN)
        self.assertEqual(r["value"], {"a": "1"})
        self.assertEqual(cmoctl.call("GET", "/v1/databases/acme/keys?key=x%3Ay", None, base, TOKEN)[0], 403)
        srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main()
