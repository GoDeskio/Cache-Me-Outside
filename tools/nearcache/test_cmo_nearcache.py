import os, socket, sys, threading, unittest
sys.path.insert(0, os.path.dirname(__file__))
import cmo_nearcache as nc


class FakeServer:
    """Answers HELLO/CLIENT/GET/SET; can inject an invalidate push."""
    def __init__(self):
        self.a, self.b = socket.socketpair()
        self.store = {b"k": b"v1"}
        self.gets = 0
        self.f = self.b.makefile("rb")
        threading.Thread(target=self.loop, daemon=True).start()

    def push_invalidate(self, keys):
        if keys is None:
            self.b.sendall(b">2\r\n$10\r\ninvalidate\r\n_\r\n")
        else:
            body = b"".join(b"$%d\r\n%s\r\n" % (len(k), k) for k in keys)
            self.b.sendall(b">2\r\n$10\r\ninvalidate\r\n*%d\r\n" % len(keys) + body)

    def loop(self):
        while True:
            try:
                cmd = nc.read(self.f)
            except Exception:
                return
            name = cmd[0].upper()
            if name == b"HELLO":
                self.b.sendall(b"%1\r\n+proto\r\n:3\r\n")
            elif name == b"GET":
                self.gets += 1
                v = self.store.get(cmd[1])
                self.b.sendall(b"_\r\n" if v is None else b"$%d\r\n%s\r\n" % (len(v), v))
            elif name == b"SET":
                self.store[cmd[1]] = cmd[2]
                self.b.sendall(b"+OK\r\n")
            else:
                self.b.sendall(b"+OK\r\n")


class T(unittest.TestCase):
    def setUp(self):
        self.s = FakeServer()
        self.c = nc.NearCache(None, sock=self.s.a, max_keys=2)

    def tearDown(self):
        self.c.close()

    def test_second_get_is_local(self):
        self.assertEqual(self.c.get("k"), b"v1")
        self.assertEqual(self.c.get("k"), b"v1")
        self.assertEqual(self.s.gets, 1)
        self.assertEqual(self.c.hits, 1)

    def test_invalidate_push_drops_key(self):
        self.c.get("k")
        self.s.store[b"k"] = b"v2"
        self.s.push_invalidate([b"k"])
        import time; time.sleep(0.05)
        self.assertEqual(self.c.get("k"), b"v2")
        self.assertEqual(self.s.gets, 2)

    def test_flush_invalidate_clears_all(self):
        self.c.get("k")
        self.s.push_invalidate(None)
        import time; time.sleep(0.05)
        self.c.get("k")
        self.assertEqual(self.s.gets, 2)

    def test_own_set_drops_local(self):
        self.c.get("k")
        self.c.set("k", "v3")
        self.assertEqual(self.c.get("k"), b"v3")

    def test_lru_bound(self):
        for k in ("a", "b", "k"):
            self.c.get(k)
        self.assertEqual(len(self.c._local), 2)
        self.assertNotIn(b"a", self.c._local)

    def test_missing_key_cached_as_none(self):
        self.assertIsNone(self.c.get("nope"))
        self.assertIsNone(self.c.get("nope"))
        self.assertEqual(self.s.gets, 1)

    def test_resp_parse_map_and_error(self):
        import io
        self.assertEqual(nc.read(io.BytesIO(b"%1\r\n+a\r\n:1\r\n")), {"a": 1})
        with self.assertRaises(nc.RespError):
            nc.read(io.BytesIO(b"-ERR x\r\n"))


if __name__ == "__main__":
    unittest.main()
