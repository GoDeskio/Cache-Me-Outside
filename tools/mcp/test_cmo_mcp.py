#!/usr/bin/env python3
"""Offline tests: a fake RESP server stands in for Valkey."""
import json
import os
import socketserver
import subprocess
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import cmo_mcp  # noqa: E402


def bulk(s):
    return b"$-1\r\n" if s is None else b"$%d\r\n%s\r\n" % (len(s.encode()), s.encode())


class Fake(socketserver.StreamRequestHandler):
    store = {}
    seen = []

    def handle(self):
        while True:
            line = self.rfile.readline()
            if not line:
                return
            args = []
            for _ in range(int(line[1:-2])):
                n = int(self.rfile.readline()[1:-2])
                args.append(self.rfile.read(n + 2)[:-2].decode())
            Fake.seen.append(args)
            cmd = args[0].upper()
            if cmd == "AUTH":
                out = b"+OK\r\n" if args[1:] == ["agent", "p@ss"] else b"-WRONGPASS bad\r\n"
            elif cmd == "GET":
                out = bulk(Fake.store.get(args[1]))
            elif cmd == "SET":
                Fake.store[args[1]] = args[2]; out = b"+OK\r\n"
            elif cmd == "DEL":
                out = b":%d\r\n" % (1 if Fake.store.pop(args[1], None) is not None else 0)
            elif cmd == "TTL":
                out = b":-1\r\n" if args[1] in Fake.store else b":-2\r\n"
            elif cmd == "SCAN":
                keys = sorted(Fake.store)
                out = b"*2\r\n" + bulk("0") + b"*%d\r\n" % len(keys) + b"".join(bulk(k) for k in keys)
            elif cmd == "INFO":
                out = bulk("# Stats\r\nkeyspace_hits:3\r\nkeyspace_misses:1\r\nused_memory:50\r\nmaxmemory:100\r\n")
            else:
                out = b"-ERR unknown\r\n"
            self.wfile.write(out)


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Fake)
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = "redis://agent:p%%40ss@127.0.0.1:%d/0" % cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Fake.store.clear(); Fake.seen.clear()

    def call(self, server, name, args=None):
        r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})
        return r["result"]

    def test_read_only_by_default(self):
        s = cmo_mcp.Server(lambda: cmo_mcp.Resp(self.url))
        names = [t["name"] for t in s.handle({"id": 1, "method": "tools/list"})["result"]["tools"]]
        self.assertNotIn("cache_set", names)
        self.assertTrue(self.call(s, "cache_set", {"key": "a", "value": "b"})["isError"])
        self.assertEqual(Fake.store, {})

    def test_write_read_scan_stats(self):
        s = cmo_mcp.Server(lambda: cmo_mcp.Resp(self.url), write=True)
        self.assertFalse(self.call(s, "cache_set", {"key": "app:a", "value": "héllo", "ttl_seconds": 60})["isError"])
        self.assertEqual(Fake.seen[-1], ["SET", "app:a", "héllo", "EX", "60"])
        self.assertEqual(Fake.seen[0], ["AUTH", "agent", "p@ss"])
        self.assertEqual(self.call(s, "cache_get", {"key": "app:a"})["structuredContent"]["value"], "héllo")
        self.assertEqual(self.call(s, "cache_scan", {"pattern": "app:*"})["structuredContent"]["keys"], ["app:a"])
        st = self.call(s, "cache_stats")["structuredContent"]
        self.assertEqual((st["hit_rate"], st["memory_ratio"]), (0.75, 0.5))
        self.assertEqual(self.call(s, "cache_delete", {"key": "app:a"})["structuredContent"]["deleted"], 1)
        self.assertIsNone(self.call(s, "cache_get", {"key": "app:a"})["structuredContent"]["value"])

    def test_bad_auth_is_a_tool_error(self):
        bad = self.url.replace("p%40ss", "nope")
        r = self.call(cmo_mcp.Server(lambda: cmo_mcp.Resp(bad)), "cache_get", {"key": "x"})
        self.assertTrue(r["isError"]); self.assertIn("WRONGPASS", r["content"][0]["text"])

    def test_stdio_handshake(self):
        env = dict(os.environ, CMO_MCP_URL=self.url)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "nope"}]
        out = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "cmo_mcp.py")],
                             input="\n".join(map(json.dumps, lines)) + "\nnot json\n", capture_output=True, text=True, env=env, timeout=10).stdout.splitlines()
        replies = [json.loads(l) for l in out]
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "cache-me-outside")
        self.assertEqual(replies[1]["error"]["code"], -32601)
        self.assertEqual(replies[2]["error"]["code"], -32700)
        self.assertEqual(len(replies), 3)

    def test_rejects_non_redis_url(self):
        with self.assertRaises(ValueError):
            cmo_mcp.Resp("http://x")


if __name__ == "__main__":
    unittest.main()
