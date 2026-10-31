import io, json, os, sys, tempfile, threading, unittest, http.server
sys.path.insert(0, os.path.dirname(__file__))
import cmo_mgmt as m
import cmoctl

TOKEN = "t" * 32


class FakeAcl:
    def __init__(self):
        self.users = {}
    def set_user(self, n, p):
        self.users[n] = p
    def delete_user(self, n):
        self.users.pop(n, None)


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cfg = os.path.join(self.d, "proxy.json")
        self.acl = FakeAcl()
        mgr = m.Manager(m.Store(self.cfg, "127.0.0.1:6379"), self.acl)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), m.make_handler(mgr, TOKEN))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close()

    def c(self, method, path, body=None, token=TOKEN):
        return cmoctl.call(method, path, body, self.base, token)

    def test_auth_required(self):
        self.assertEqual(self.c("GET", "/v1/databases", token="nope")[0], 401)

    def test_create_list_get(self):
        st, r = self.c("POST", "/v1/databases", {"name": "acme", "ops_per_sec": 100})
        self.assertEqual(st, 201)
        self.assertEqual(r["port"], 7001)
        self.assertEqual(self.acl.users["acme"], r["password"])
        cfg = json.load(open(self.cfg))
        self.assertEqual(cfg["tenants"]["acme"]["ops_per_sec"], 100)
        self.assertNotIn("password", json.dumps(cfg))
        self.assertEqual(self.c("GET", "/v1/databases")[1]["databases"][0]["name"], "acme")
        self.assertNotIn("password", self.c("GET", "/v1/databases/acme")[1])

    def test_ports_allocate_and_conflict(self):
        self.c("POST", "/v1/databases", {"name": "aa"})
        self.assertEqual(self.c("POST", "/v1/databases", {"name": "bb"})[1]["port"], 7002)
        self.assertEqual(self.c("POST", "/v1/databases", {"name": "cc", "port": 7001})[0], 400)
        self.assertEqual(self.c("POST", "/v1/databases", {"name": "aa"})[0], 409)

    def test_name_validation(self):
        for bad in ("A", "default", "x", "a b", "../etc", 5):
            self.assertEqual(self.c("POST", "/v1/databases", {"name": bad})[0], 400, bad)

    def test_limits_validation_and_patch(self):
        self.assertEqual(self.c("POST", "/v1/databases", {"name": "aa", "max_conns": -1})[0], 400)
        self.c("POST", "/v1/databases", {"name": "aa"})
        st, r = self.c("PATCH", "/v1/databases/aa", {"max_conns": 5})
        self.assertEqual((st, r["max_conns"]), (200, 5))
        self.assertEqual(self.c("PATCH", "/v1/databases/aa", {})[0], 400)

    def test_rotate_and_delete(self):
        p1 = self.c("POST", "/v1/databases", {"name": "aa"})[1]["password"]
        p2 = self.c("POST", "/v1/databases/aa/rotate-password", {})[1]["password"]
        self.assertNotEqual(p1, p2)
        self.assertEqual(self.acl.users["aa"], p2)
        self.assertEqual(self.c("DELETE", "/v1/databases/aa")[0], 200)
        self.assertNotIn("aa", self.acl.users)
        self.assertEqual(self.c("GET", "/v1/databases/aa")[0], 404)

    def test_openapi(self):
        self.assertIn("/v1/databases", self.c("GET", "/v1/openapi.json")[1]["paths"])

    def test_cli(self):
        os.environ["CMO_API"], os.environ["CMO_ADMIN_TOKEN"] = self.base, TOKEN
        out = io.StringIO()
        self.assertEqual(cmoctl.main(["create", "acme", "--ops-per-sec", "9"], out), 0)
        self.assertEqual(json.loads(out.getvalue())["ops_per_sec"], 9)
        self.assertEqual(cmoctl.main(["delete", "acme"], io.StringIO()), 2)
        self.assertEqual(cmoctl.main(["get", "nope"], io.StringIO()), 1)

    def test_proxy_can_load_written_config(self):
        self.c("POST", "/v1/databases", {"name": "aa", "ops_per_sec": 10})
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxy"))
        import cmo_proxy
        ts = cmo_proxy.load(self.cfg)
        self.assertEqual(ts[0].name, "aa")


if __name__ == "__main__":
    unittest.main()
