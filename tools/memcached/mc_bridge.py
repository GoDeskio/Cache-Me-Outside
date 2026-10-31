#!/usr/bin/env python3
"""Memcached text-protocol listener over Cache-Me-Outside (plan item 2).

Written from the public protocol description; no memcached code used.
Supports: get/gets, set/add/replace/append/prepend, delete, incr/decr,
touch, flush_all (off unless MC_ALLOW_FLUSH=1), version, quit.
Keys map to "<prefix><key>" strings; memcached flags are stored in a
"<prefix>f:<key>" sibling. CAS is not supported (gets returns cas 0).

  MC_LISTEN=127.0.0.1:11211 CMO_UPSTREAM=127.0.0.1:6379 MC_PREFIX=mc: python3 mc_bridge.py
"""
import asyncio
import os


async def resp(reader, writer, *args):
    writer.write(b"*%d\r\n" % len(args) + b"".join(
        b"$%d\r\n%s\r\n" % (len(a), a) for a in (x if isinstance(x, bytes) else str(x).encode() for x in args)))
    await writer.drain()
    return await read_reply(reader)


async def read_reply(r):
    line = (await r.readline())[:-2]
    t, rest = line[:1], line[1:]
    if t == b"+":
        return rest
    if t == b"-":
        raise RuntimeError(rest.decode())
    if t == b":":
        return int(rest)
    if t == b"$":
        n = int(rest)
        return None if n < 0 else (await r.readexactly(n + 2))[:-2]
    if t == b"*":
        return [await read_reply(r) for _ in range(int(rest))]
    raise RuntimeError("bad reply")


def exptime(e):
    e = int(e)
    if e < 0:
        return -1
    if e > 60 * 60 * 24 * 30:  # absolute unix time per memcached rules
        return ("PXAT", e * 1000)
    return ("EX", e) if e else None


class Session:
    def __init__(self, up_r, up_w, prefix, allow_flush):
        self.r, self.w, self.p, self.allow_flush = up_r, up_w, prefix.encode(), allow_flush

    def k(self, key):
        return self.p + key

    def fk(self, key):
        return self.p + b"f:" + key

    async def call(self, *a):
        return await resp(self.r, self.w, *a)

    async def store(self, cmd, key, flags, exp, data):
        e = exptime(exp)
        if e == -1:
            await self.call("DEL", self.k(key), self.fk(key))
            return b"STORED" if cmd == b"set" else b"NOT_STORED"
        if cmd in (b"append", b"prepend"):
            cur = await self.call("GET", self.k(key))
            if cur is None:
                return b"NOT_STORED"
            data = cur + data if cmd == b"append" else data + cur
            await self.call("SET", self.k(key), data, "KEEPTTL")
            return b"STORED"
        extra = list(e) if e else []
        cond = {b"add": ["NX"], b"replace": ["XX"]}.get(cmd, [])
        ok = await self.call("SET", self.k(key), data, *cond, *extra)
        if ok is None:
            return b"NOT_STORED"
        if flags != b"0":
            await self.call("SET", self.fk(key), flags, *extra)
        else:
            await self.call("DEL", self.fk(key))
        return b"STORED"

    async def handle(self, line, client_r):
        parts = line.split()
        if not parts:
            return b"ERROR"
        c = parts[0].lower()
        if c in (b"get", b"gets"):
            if len(parts) < 2:
                return b"ERROR"
            out = []
            for key in parts[1:]:
                v = await self.call("GET", self.k(key))
                if v is None:
                    continue
                f = await self.call("GET", self.fk(key)) or b"0"
                out.append(b"VALUE %s %s %d%s\r\n%s" % (key, f, len(v), b" 0" if c == b"gets" else b"", v))
            return b"\r\n".join(out + [b"END"])
        if c in (b"set", b"add", b"replace", b"append", b"prepend"):
            if len(parts) < 5 or len(parts[1]) > 250:
                return b"CLIENT_ERROR bad command line format"
            n = int(parts[4])
            data = (await client_r.readexactly(n + 2))[:-2]
            res = await self.store(c, parts[1], parts[2], parts[3], data)
            return None if parts[-1] == b"noreply" else res
        if c == b"delete" and len(parts) >= 2:
            n = await self.call("DEL", self.k(parts[1]), self.fk(parts[1]))
            return b"DELETED" if n else b"NOT_FOUND"
        if c in (b"incr", b"decr") and len(parts) >= 3:
            if await self.call("EXISTS", self.k(parts[1])) == 0:
                return b"NOT_FOUND"
            try:
                if c == b"incr":
                    v = await self.call("INCRBY", self.k(parts[1]), int(parts[2]))
                else:  # memcached decr floors at 0
                    cur = int(await self.call("GET", self.k(parts[1])))
                    v = max(0, cur - int(parts[2]))
                    await self.call("SET", self.k(parts[1]), v, "KEEPTTL")
            except (RuntimeError, ValueError):
                return b"CLIENT_ERROR cannot increment or decrement non-numeric value"
            return str(v).encode()
        if c == b"touch" and len(parts) >= 3:
            e = exptime(parts[2])
            if e == -1:
                n = await self.call("DEL", self.k(parts[1]))
            elif e:
                n = await self.call("PEXPIREAT" if e[0] == "PXAT" else "EXPIRE", self.k(parts[1]), e[1])
            else:
                n = await self.call("PERSIST", self.k(parts[1])) or await self.call("EXISTS", self.k(parts[1]))
            return b"TOUCHED" if n else b"NOT_FOUND"
        if c == b"flush_all":
            if not self.allow_flush:
                return b"SERVER_ERROR flush_all is disabled"
            cur = b"0"
            while True:
                cur, keys = await self.call("SCAN", cur, "MATCH", self.p + b"*", "COUNT", 500)
                if keys:
                    await self.call("UNLINK", *keys)
                if cur == b"0":
                    return b"OK"
        if c == b"version":
            return b"VERSION cmo-mc-bridge 0.1"
        return b"ERROR"


async def serve_client(cr, cw, upstream, prefix, allow_flush, auth):
    host, port = upstream.rsplit(":", 1)
    ur, uw = await asyncio.open_connection(host, int(port))
    s = Session(ur, uw, prefix, allow_flush)
    try:
        if auth:
            await s.call("AUTH", *auth)
        while True:
            line = await cr.readline()
            if not line:
                break
            line = line.rstrip(b"\r\n")
            if line.lower() == b"quit":
                break
            try:
                out = await s.handle(line, cr)
            except RuntimeError as e:
                out = b"SERVER_ERROR " + str(e).encode()
            except ValueError:
                out = b"CLIENT_ERROR bad command line format"
            if out is not None:
                cw.write(out + b"\r\n")
                await cw.drain()
    finally:
        uw.close()
        cw.close()


async def main():
    host, port = os.environ.get("MC_LISTEN", "127.0.0.1:11211").rsplit(":", 1)
    auth = None
    if os.environ.get("CMO_PASS_FILE"):
        auth = (os.environ.get("CMO_USER", "default"), open(os.environ["CMO_PASS_FILE"]).read().strip())
    srv = await asyncio.start_server(
        lambda r, w: serve_client(r, w, os.environ.get("CMO_UPSTREAM", "127.0.0.1:6379"),
                                  os.environ.get("MC_PREFIX", "mc:"), os.environ.get("MC_ALLOW_FLUSH") == "1", auth),
        host, int(port))
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
