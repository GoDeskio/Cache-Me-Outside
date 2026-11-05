import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import cmo_proxy as p


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class BucketTest(unittest.TestCase):
    def test_rate(self):
        c = Clock()
        b = p.Bucket(10, c)
        self.assertEqual(b.take(10), 0.0)
        self.assertAlmostEqual(b.take(5), 0.5)
        c.t = 1.0
        self.assertEqual(b.take(1), 0.0)

    def test_unlimited(self):
        self.assertEqual(p.Bucket(0).take(10**9), 0.0)


class CounterTest(unittest.TestCase):
    def test_split_and_inline(self):
        c = p.CommandCounter()
        cmd = b"*2\r\n$3\r\nGET\r\n$1\r\nk\r\n"
        self.assertEqual(c.feed(cmd[:7]), 0)
        self.assertEqual(c.feed(cmd[7:] + cmd + b"PING\r\n"), 3)
        self.assertEqual(c.feed(b"*1\r\n$4\r\nPI"), 0)
        self.assertEqual(c.feed(b"NG\r\n"), 1)

    def test_bad(self):
        with self.assertRaises(ValueError):
            p.CommandCounter().feed(b"*1\r\n:5\r\n")


class Echo:
    """Fake upstream: replies +OK to every command."""

    async def start(self):
        async def h(r, w):
            c = p.CommandCounter()
            while data := await r.read(65536):
                w.write(b"+OK\r\n" * c.feed(data))
                await w.drain()
            w.close()
        self.server = await asyncio.start_server(h, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]


class Deny(p.Budget):
    def __init__(self):
        self.ok = True

    def allow(self, tenant):
        return self.ok


class ProxyTest(unittest.IsolatedAsyncioTestCase):
    async def setUp_(self, cfg, budget=None):
        up = await Echo().start()
        cfg = {"listen": "127.0.0.1:0", "upstream": f"127.0.0.1:{up}", **cfg}
        t = p.Tenant("acme", cfg, budget=budget)
        (srv,) = await p.serve([t])
        return t, srv.sockets[0].getsockname()[1]

    async def test_forward_and_conn_limit(self):
        t, port = await self.setUp_({"max_conns": 1})
        r1, w1 = await asyncio.open_connection("127.0.0.1", port)
        w1.write(b"PING\r\n")
        self.assertEqual(await r1.readline(), b"+OK\r\n")
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        self.assertIn(b"max connections", await r2.readline())
        w1.close()
        await asyncio.sleep(0.05)
        self.assertEqual(t.conns, 0)

    async def test_ops_limit_slows(self):
        _, port = await self.setUp_({"ops_per_sec": 20})
        r, w = await asyncio.open_connection("127.0.0.1", port)
        loop = asyncio.get_running_loop()
        start = loop.time()
        for _ in range(3):
            w.write(b"PING\r\n" * 15)
            for _ in range(15):
                await r.readline()
        self.assertGreater(loop.time() - start, 1.0)
        w.close()

    async def test_budget_blocks(self):
        b = Deny()
        _, port = await self.setUp_({}, budget=b)
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"PING\r\n")
        self.assertEqual(await r.readline(), b"+OK\r\n")
        b.ok = False
        w.write(b"PING\r\n")
        self.assertIn(b"budget cap", await r.readline())
        w.close()


class ReloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_add_change_remove(self):
        import json, socket, tempfile
        d = tempfile.mkdtemp(); path = os.path.join(d, "c.json")
        r = p.Reloader(path)
        self.assertTrue(await r.check())           # missing file: no listeners
        self.assertEqual(r.servers, {})
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        cfg = {"tenants": {"a": {"listen": "127.0.0.1:%d" % port, "upstream": "127.0.0.1:1"}}}
        json.dump(cfg, open(path, "w"))
        await r.check()
        self.assertIn("a", r.servers)
        first = r.servers["a"]
        self.assertFalse(await r.check())          # unchanged
        cfg["tenants"]["a"]["ops_per_sec"] = 5
        json.dump(cfg, open(path, "w")); os.utime(path, ns=(1, 1))
        await r.check()
        self.assertIsNot(r.servers["a"], first)     # changed: new listener
        json.dump({"tenants": {}}, open(path, "w")); os.utime(path, ns=(2, 2))
        await r.check()
        self.assertEqual(r.servers, {})


if __name__ == "__main__":
    unittest.main()
