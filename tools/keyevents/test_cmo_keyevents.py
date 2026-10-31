#!/usr/bin/env python3
"""Offline tests: fake RESP server publishes key events; webhook is a fake opener."""
import os
import socketserver
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import cmo_keyevents as k  # noqa: E402


def bulk(s):
    return b"$%d\r\n%s\r\n" % (len(s), s.encode())


class Fake(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline()
        args = []
        for _ in range(int(line[1:-2])):
            n = int(self.rfile.readline()[1:-2]); args.append(self.rfile.read(n + 2)[:-2].decode())
        Fake.subscribed = args[1:]
        for ch in args[1:]:
            self.wfile.write(b"*3\r\n" + bulk("subscribe") + bulk(ch) + b":1\r\n")
        for ch, key in [("__keyevent@0__:set", "orders:1"), ("__keyevent@0__:expired", "sess:9"), ("__keyevent@0__:del", "orders:2")]:
            self.wfile.write(b"*3\r\n" + bulk("message") + bulk(ch) + bulk(key))
        self.wfile.flush()


class Resp:
    def __init__(self, status): self.status = status
    def __enter__(self): return self
    def __exit__(self, *a): pass


class T(unittest.TestCase):
    def test_sign_verify(self):
        h = k.sign("s" * 16, b"{}", 1000)
        self.assertTrue(k.verify("s" * 16, b"{}", h, 1100))
        self.assertFalse(k.verify("s" * 16, b"{}", h, 2000))
        self.assertFalse(k.verify("x" * 16, b"{}", h, 1000))
        self.assertFalse(k.verify("s" * 16, b"{}", "junk", 1000))

    def test_filter(self):
        self.assertEqual(k.to_event("__keyevent@3__:del", "a:1", "a:*", ("del",)), {"type": "del", "key": "a:1", "db": 3})
        self.assertIsNone(k.to_event("__keyevent@0__:del", "b", "a:*", ("del",)))
        self.assertIsNone(k.to_event("__keyevent@0__:hset", "a", "*", ("del",)))
        self.assertIsNone(k.to_event("other", "a", "*", ("del",)))

    def test_subscribe_stream(self):
        srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Fake)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            sub = k.Sub("redis://127.0.0.1:%d/0" % srv.server_address[1], timeout=5)
            got = []
            for ch, key in sub.events(("set", "del")):
                got.append(k.to_event(ch, key, "orders:*", ("set", "del")))
                if len(got) == 3:
                    break
            self.assertEqual(Fake.subscribed, ["__keyevent@0__:set", "__keyevent@0__:del"])
            self.assertEqual([g and g["key"] for g in got], ["orders:1", None, "orders:2"])
            sub.s.close()
        finally:
            srv.shutdown(); srv.server_close()

    def test_post_retries_and_signs(self):
        calls = []
        def opener(req, timeout):
            calls.append(req)
            if len(calls) < 2:
                raise OSError("down")
            return Resp(204)
        self.assertTrue(k.post("https://h", "s" * 16, {"type": "set", "key": "a"}, opener=opener, sleep=lambda s: None))
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].get_header("X-cmo-signature").startswith("t="))
        self.assertFalse(k.post("https://h", "s" * 16, {}, opener=lambda r, timeout: Resp(400), sleep=lambda s: None))

    def test_main_refuses_http(self):
        os.environ.update(CMO_EVENTS_URL="redis://x", CMO_EVENTS_WEBHOOK="http://h", CMO_EVENTS_SECRET="s" * 16)
        self.assertEqual(k.main(), 1)


if __name__ == "__main__":
    unittest.main()
