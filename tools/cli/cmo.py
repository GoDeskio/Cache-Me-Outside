"""cmo: data-plane CLI for Cache Me Outside (plan #128).

It sits alongside cmoctl (#23), which covers the management plane. Stdlib only, RESP2.

  cmo [-H host] [-p port] [-a] COMMAND ...
    get KEY | set KEY VAL [--ttl S] | del KEY.. | ttl KEY | expire KEY S
    keys [PATTERN] [--limit N]     SCAN-based, never KEYS
    stats                          hit rate, memory, ops/s, clients
    info [SECTION] | config get PARAM | config set PARAM VAL
    slowlog [N] | clients | dbsize | ping
    flush --yes                    FLUSHDB (refused without --yes)
    raw CMD ARG..                  any command

-a reads the password from CMO_PASSWORD. It is never taken from argv, so it stays out of ps.
"""
import argparse
import json
import os
import socket
import sys


class Resp:
    def __init__(self, host, port, timeout=5):
        self.s = socket.create_connection((host, port), timeout)
        self.f = self.s.makefile("rb")

    def close(self):
        self.f.close(); self.s.close()

    def call(self, *args):
        out = b"*%d\r\n" % len(args)
        for a in args:
            a = a if isinstance(a, bytes) else str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        self.s.sendall(out)
        return self.read()

    def read(self):
        line = self.f.readline()
        if not line:
            raise ConnectionError("server closed connection")
        t, body = line[:1], line[1:-2]
        if t == b"+": return body.decode()
        if t == b"-": raise RuntimeError(body.decode())
        if t == b":": return int(body)
        if t == b"$":
            n = int(body)
            if n < 0: return None
            data = self.f.read(n + 2)[:-2]
            return data.decode("utf-8", "replace")
        if t == b"*":
            n = int(body)
            return None if n < 0 else [self.read() for _ in range(n)]
        raise ValueError("bad reply %r" % line)


def parse_info(text):
    d = {}
    for ln in text.splitlines():
        if ":" in ln and not ln.startswith("#"):
            k, v = ln.split(":", 1); d[k] = v
    return d


def stats(info):
    h, m = int(info.get("keyspace_hits", 0)), int(info.get("keyspace_misses", 0))
    return {"hit_rate": round(h / (h + m), 4) if h + m else None, "hits": h, "misses": m,
            "used_memory": int(info.get("used_memory", 0)), "maxmemory": int(info.get("maxmemory", 0)),
            "ops_per_sec": int(info.get("instantaneous_ops_per_sec", 0)),
            "clients": int(info.get("connected_clients", 0)), "evicted": int(info.get("evicted_keys", 0))}


def scan(c, pattern, limit):
    cur, out = "0", []
    while True:
        cur, keys = c.call("SCAN", cur, "MATCH", pattern, "COUNT", 500)
        out.extend(keys)
        if cur == "0" or len(out) >= limit:
            return out[:limit]


def build():
    p = argparse.ArgumentParser(prog="cmo")
    p.add_argument("-H", "--host", default=os.environ.get("CMO_HOST", "127.0.0.1"))
    p.add_argument("-p", "--port", type=int, default=int(os.environ.get("CMO_PORT", 6379)))
    p.add_argument("-a", "--auth", action="store_true")
    p.add_argument("--json", action="store_true")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("get").add_argument("key")
    s = sp.add_parser("set"); s.add_argument("key"); s.add_argument("value"); s.add_argument("--ttl", type=int)
    sp.add_parser("del").add_argument("keys", nargs="+")
    sp.add_parser("ttl").add_argument("key")
    s = sp.add_parser("expire"); s.add_argument("key"); s.add_argument("seconds", type=int)
    s = sp.add_parser("keys"); s.add_argument("pattern", nargs="?", default="*"); s.add_argument("--limit", type=int, default=100)
    for n in ("stats", "clients", "dbsize", "ping"): sp.add_parser(n)
    sp.add_parser("info").add_argument("section", nargs="?")
    s = sp.add_parser("config"); s.add_argument("op", choices=["get", "set"]); s.add_argument("param"); s.add_argument("value", nargs="?")
    sp.add_parser("slowlog").add_argument("n", nargs="?", type=int, default=10)
    sp.add_parser("flush").add_argument("--yes", action="store_true")
    sp.add_parser("raw").add_argument("args", nargs="+")
    return p


def run(a, c):
    if a.auth:
        c.call("AUTH", os.environ["CMO_PASSWORD"])
    k = a.cmd
    if k == "get": return c.call("GET", a.key)
    if k == "set": return c.call("SET", a.key, a.value, *(["EX", a.ttl] if a.ttl else []))
    if k == "del": return c.call("DEL", *a.keys)
    if k == "ttl": return c.call("TTL", a.key)
    if k == "expire": return c.call("EXPIRE", a.key, a.seconds)
    if k == "keys": return scan(c, a.pattern, a.limit)
    if k == "stats": return stats(parse_info(c.call("INFO")))
    if k == "info": return parse_info(c.call("INFO", *([a.section] if a.section else [])))
    if k == "config":
        if a.op == "set":
            if a.value is None: raise SystemExit("config set needs a value")
            return c.call("CONFIG", "SET", a.param, a.value)
        r = c.call("CONFIG", "GET", a.param); return dict(zip(r[::2], r[1::2]))
    if k == "slowlog": return c.call("SLOWLOG", "GET", a.n)
    if k == "clients": return c.call("CLIENT", "LIST").splitlines()
    if k == "dbsize": return c.call("DBSIZE")
    if k == "ping": return c.call("PING")
    if k == "flush":
        if not a.yes: raise SystemExit("refusing to FLUSHDB without --yes")
        return c.call("FLUSHDB")
    return c.call(*a.args)


def main(argv=None):
    a = build().parse_args(argv)
    if a.cmd == "flush" and not a.yes:
        print("refusing to FLUSHDB without --yes", file=sys.stderr); return 2
    c = Resp(a.host, a.port)
    try:
        r = run(a, c)
    except RuntimeError as e:
        print("error:", e, file=sys.stderr); return 1
    finally:
        c.close()
    if a.json or isinstance(r, (dict, list)):
        print(json.dumps(r, indent=None if a.json else 2))
    else:
        print("(nil)" if r is None else r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
