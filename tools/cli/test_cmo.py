import io
import socketserver
import threading
import unittest
from contextlib import redirect_stdout, redirect_stderr
import cmo

STORE, LOG = {}, []


class H(socketserver.StreamRequestHandler):
    def rd(self):
        n = int(self.rfile.readline()[1:])
        args = []
        for _ in range(n):
            ln = int(self.rfile.readline()[1:]); args.append(self.rfile.read(ln + 2)[:-2].decode())
        return args

    def bulk(self, s): return b"$-1\r\n" if s is None else b"$%d\r\n%s\r\n" % (len(s.encode()), s.encode())

    def handle(self):
        while True:
            try: a = self.rd()
            except Exception: return
            LOG.append(a); c = a[0].upper()
            if c == "GET": r = self.bulk(STORE.get(a[1]))
            elif c == "SET": STORE[a[1]] = a[2]; r = b"+OK\r\n"
            elif c == "DEL": r = b":%d\r\n" % sum(STORE.pop(k, None) is not None for k in a[1:])
            elif c == "SCAN":
                if a[1] == "0": r = b"*2\r\n$1\r\n7\r\n*1\r\n" + self.bulk("k1")
                else: r = b"*2\r\n$1\r\n0\r\n*1\r\n" + self.bulk("k2")
            elif c == "INFO": r = self.bulk("# Stats\r\nkeyspace_hits:3\r\nkeyspace_misses:1\r\nused_memory:10\r\nconnected_clients:2")
            elif c == "CONFIG": r = b"*2\r\n" + self.bulk("maxmemory") + self.bulk("100")
            elif c == "FLUSHDB": STORE.clear(); r = b"+OK\r\n"
            else: r = b"-ERR unknown\r\n"
            self.wfile.write(r)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        socketserver.ThreadingTCPServer.allow_reuse_address = True
        cls.s = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); cls.s.daemon_threads = True
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()
        cls.port = str(cls.s.server_address[1])

    @classmethod
    def tearDownClass(cls): cls.s.shutdown(); cls.s.server_close()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cmo.main(["-p", self.port, *args])
        return rc, out.getvalue().strip(), err.getvalue()

    def test_set_get_ttl_del(self):
        self.run_cli("set", "a", "1", "--ttl", "9")
        self.assertEqual(LOG[-1], ["SET", "a", "1", "EX", "9"])
        self.assertEqual(self.run_cli("get", "a")[1], "1")
        self.assertEqual(self.run_cli("del", "a")[1], "1")
        self.assertEqual(self.run_cli("get", "a")[1], "(nil)")

    def test_keys_uses_scan_and_stats(self):
        self.assertIn('"k2"', self.run_cli("keys", "k*")[1])
        self.assertFalse(any(x[0] == "KEYS" for x in LOG))
        self.assertIn('"hit_rate": 0.75', self.run_cli("--json", "stats")[1])
        self.assertIn('"maxmemory": "100"', self.run_cli("config", "get", "maxmemory")[1])

    def test_flush_guard_and_errors(self):
        STORE["x"] = "1"
        self.assertEqual(self.run_cli("flush")[0], 2); self.assertIn("x", STORE)
        self.assertEqual(self.run_cli("flush", "--yes")[0], 0); self.assertNotIn("x", STORE)
        rc, _, err = self.run_cli("raw", "BOGUS")
        self.assertEqual(rc, 1); self.assertIn("ERR", err)


if __name__ == "__main__":
    unittest.main()
