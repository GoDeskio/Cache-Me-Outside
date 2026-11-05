import asyncio
import unittest
import mc_bridge as M


class FakeValkey:
    """In-memory RESP server with the commands the bridge uses."""
    def __init__(self):
        self.d, self.ttl = {}, {}

    def run(self, a):
        c = a[0].upper()
        if c == b"GET":
            return self.d.get(a[1])
        if c == b"SET":
            k, v, opts = a[1], a[2], [x.upper() for x in a[3:]]
            if b"NX" in opts and k in self.d or b"XX" in opts and k not in self.d:
                return None
            self.d[k] = v
            if b"EX" in opts:
                self.ttl[k] = int(a[3 + opts.index(b"EX") + 1])
            return "OK"
        if c in (b"DEL", b"UNLINK"):
            return sum(self.d.pop(k, None) is not None for k in a[1:])
        if c == b"EXISTS":
            return int(a[1] in self.d)
        if c == b"INCRBY":
            try:
                v = int(self.d.get(a[1], b"0")) + int(a[2])
            except ValueError:
                raise RuntimeError("ERR not an integer")
            self.d[a[1]] = str(v).encode()
            return v
        if c in (b"EXPIRE", b"PERSIST", b"PEXPIREAT"):
            return int(a[1] in self.d)
        if c == b"SCAN":
            return [b"0", [k for k in self.d if k.startswith(a[3][:-1])]]
        raise RuntimeError("ERR unknown")

    def enc(self, v):
        if v is None:
            return b"$-1\r\n"
        if isinstance(v, int):
            return b":%d\r\n" % v
        if isinstance(v, str):
            return b"+%s\r\n" % v.encode()
        if isinstance(v, list):
            return b"*%d\r\n" % len(v) + b"".join(self.enc(x) for x in v)
        return b"$%d\r\n%s\r\n" % (len(v), v)

    async def serve(self, r, w):
        while True:
            line = await r.readline()
            if not line:
                return
            args = []
            for _ in range(int(line[1:])):
                n = int((await r.readline())[1:])
                args.append((await r.readexactly(n + 2))[:-2])
            try:
                w.write(self.enc(self.run(args)))
            except RuntimeError as e:
                w.write(b"-%s\r\n" % str(e).encode())
            await w.drain()


class T(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fv = FakeValkey()
        self.vs = await asyncio.start_server(self.fv.serve, "127.0.0.1", 0)
        up = "127.0.0.1:%d" % self.vs.sockets[0].getsockname()[1]
        self.ms = await asyncio.start_server(
            lambda r, w: M.serve_client(r, w, up, "mc:", False, None), "127.0.0.1", 0)
        self.r, self.w = await asyncio.open_connection("127.0.0.1", self.ms.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        self.w.close()
        self.ms.close()
        self.vs.close()

    async def say(self, s, lines=1):
        self.w.write(s)
        await self.w.drain()
        return b"".join([await asyncio.wait_for(self.r.readline(), 2) for _ in range(lines)])

    async def test_set_get_flags_ttl(self):
        self.assertEqual(await self.say(b"set a 5 60 3\r\nabc\r\n"), b"STORED\r\n")
        self.assertEqual(await self.say(b"get a b\r\n", 3), b"VALUE a 5 3\r\nabc\r\nEND\r\n")
        self.assertEqual(self.fv.ttl[b"mc:a"], 60)
        self.assertEqual(await self.say(b"gets a\r\n", 3), b"VALUE a 5 3 0\r\nabc\r\nEND\r\n")

    async def test_add_replace_append_delete(self):
        self.assertEqual(await self.say(b"replace x 0 0 1\r\n1\r\n"), b"NOT_STORED\r\n")
        self.assertEqual(await self.say(b"add x 0 0 1\r\n1\r\n"), b"STORED\r\n")
        self.assertEqual(await self.say(b"add x 0 0 1\r\n2\r\n"), b"NOT_STORED\r\n")
        self.assertEqual(await self.say(b"append x 0 0 2\r\nyz\r\n"), b"STORED\r\n")
        self.assertEqual(self.fv.d[b"mc:x"], b"1yz")
        self.assertEqual(await self.say(b"delete x\r\n"), b"DELETED\r\n")
        self.assertEqual(await self.say(b"delete x\r\n"), b"NOT_FOUND\r\n")

    async def test_incr_decr(self):
        await self.say(b"set n 0 0 2\r\n10\r\n")
        self.assertEqual(await self.say(b"incr n 5\r\n"), b"15\r\n")
        self.assertEqual(await self.say(b"decr n 100\r\n"), b"0\r\n")
        self.assertEqual(await self.say(b"incr nope 1\r\n"), b"NOT_FOUND\r\n")

    async def test_noreply_flush_unknown(self):
        self.w.write(b"set q 0 0 1 noreply\r\nz\r\n")
        self.assertEqual(await self.say(b"version\r\n"), b"VERSION cmo-mc-bridge 0.1\r\n")
        self.assertEqual(self.fv.d[b"mc:q"], b"z")
        self.assertTrue((await self.say(b"flush_all\r\n")).startswith(b"SERVER_ERROR"))
        self.assertEqual(await self.say(b"bogus\r\n"), b"ERROR\r\n")


if __name__ == "__main__":
    unittest.main()
