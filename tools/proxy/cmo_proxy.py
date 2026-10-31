#!/usr/bin/env python3
"""Minimal per-tenant limiting proxy for Cache Me Outside (plan item 38).

Each tenant gets its own listening port in front of its own upstream
database. The proxy forwards bytes unchanged and enforces three limits:

  max_conns       extra connections are refused with a RESP error
  ops_per_sec     commands are counted (RESP arrays and inline commands) and
                  the client is slowed down, not disconnected, when over
  bytes_per_sec   client->server and server->client bytes, shaped the same way

Config (JSON):
  {"tenants": {"acme": {"listen": "0.0.0.0:7001", "upstream": "127.0.0.1:6379",
                        "max_conns": 50, "ops_per_sec": 1000,
                        "bytes_per_sec": 5000000}}}
Any limit may be 0 or omitted to mean unlimited. Optional spending caps:
  "budget": {"url": "https://billing.example/api"} or {"file": "caps.json"}
(see cmo_budget.py). Standard library only.

  python3 cmo_proxy.py config.json
"""
import asyncio
import json
import sys
import time


class Bucket:
    """Token bucket. take(n) returns seconds to wait before n tokens are available."""

    def __init__(self, rate, clock=time.monotonic):
        self.rate = float(rate or 0)
        self.clock = clock
        self.tokens = self.rate
        self.last = clock()

    def take(self, n):
        if self.rate <= 0:
            return 0.0
        now = self.clock()
        self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
        self.last = now
        self.tokens -= n
        return 0.0 if self.tokens >= 0 else -self.tokens / self.rate


class CommandCounter:
    """Counts complete client commands in a byte stream (RESP2/3 arrays or inline)."""

    def __init__(self):
        self.buf = b""

    def feed(self, data):
        self.buf += data
        count = 0
        while True:
            used = self._one(self.buf)
            if used is None:
                break
            self.buf = self.buf[used:]
            count += 1
        if len(self.buf) > 64 * 1024 * 1024:
            raise ValueError("command too large")
        return count

    @staticmethod
    def _line(buf, pos):
        end = buf.find(b"\r\n", pos)
        return (None, None) if end < 0 else (buf[pos:end], end + 2)

    def _one(self, buf):
        if not buf:
            return None
        if buf[:1] != b"*":
            line, nxt = self._line(buf, 0)
            if line is None:
                end = buf.find(b"\n")
                return None if end < 0 else end + 1
            return nxt
        head, pos = self._line(buf, 0)
        if head is None:
            return None
        n = int(head[1:])
        for _ in range(max(n, 0)):
            h, p = self._line(buf, pos)
            if h is None:
                return None
            if h[:1] != b"$":
                raise ValueError("bad bulk header")
            size = int(h[1:])
            if len(buf) < p + size + 2:
                return None
            pos = p + size + 2
        return pos


class Budget:
    """Spending-cap hook (plan item 44). allow(tenant) False blocks commands."""

    def allow(self, tenant):
        return True


class Tenant:
    def __init__(self, name, cfg, clock=time.monotonic, budget=None):
        self.name = name
        self.max_conns = int(cfg.get("max_conns") or 0)
        self.ops = Bucket(cfg.get("ops_per_sec"), clock)
        self.bw = Bucket(cfg.get("bytes_per_sec"), clock)
        self.conns = 0
        self.budget = budget or Budget()
        host, _, port = cfg["upstream"].rpartition(":")
        self.upstream = (host, int(port))
        lhost, _, lport = cfg["listen"].rpartition(":")
        self.listen = (lhost, int(lport))

    def admit(self):
        if self.max_conns and self.conns >= self.max_conns:
            return False
        self.conns += 1
        return True

    def release(self):
        self.conns -= 1


async def _pump(reader, writer, tenant, counter=None, client=None):
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            if counter is not None:
                n = counter.feed(data)
                if n and not tenant.budget.allow(tenant.name):
                    client.write(b"-ERR budget cap reached for this database\r\n" * n)
                    await client.drain()
                    continue
                wait = tenant.ops.take(n) if n else 0.0
                if wait:
                    await asyncio.sleep(wait)
            wait = tenant.bw.take(len(data))
            if wait:
                await asyncio.sleep(wait)
            writer.write(data)
            await writer.drain()
    except (ConnectionError, ValueError):
        pass
    finally:
        writer.close()


async def handle(tenant, creader, cwriter):
    if not tenant.admit():
        cwriter.write(b"-ERR max connections reached for this database\r\n")
        await cwriter.drain()
        cwriter.close()
        return
    try:
        ureader, uwriter = await asyncio.open_connection(*tenant.upstream)
    except OSError:
        tenant.release()
        cwriter.write(b"-ERR upstream unavailable\r\n")
        cwriter.close()
        return
    try:
        await asyncio.gather(
            _pump(creader, uwriter, tenant, CommandCounter(), cwriter),
            _pump(ureader, cwriter, tenant),
        )
    finally:
        tenant.release()


def load(path, budget=None):
    with open(path) as f:
        cfg = json.load(f)
    return [Tenant(n, c, budget=budget) for n, c in cfg["tenants"].items()]


async def serve(tenants):
    servers = []
    for t in tenants:
        servers.append(await asyncio.start_server(
            lambda r, w, t=t: handle(t, r, w), *t.listen))
    return servers


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    with open(argv[1]) as f:
        cfg = json.load(f)
    budget = None
    b = cfg.get("budget")
    if b:
        import cmo_budget
        src = (cmo_budget.HttpCapSource(b["url"]) if "url" in b
               else cmo_budget.FileCapSource(b["file"]))
        budget = cmo_budget.BudgetGuard(src, ttl=b.get("ttl", 30),
                                        fail_open=b.get("fail_open", True))
    tenants = load(argv[1], budget=budget)

    async def run():
        servers = await serve(tenants)
        await asyncio.gather(*(s.serve_forever() for s in servers))

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
