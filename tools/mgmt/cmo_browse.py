"""Read-only key browser for one database (REA plan item 62).

Only reads keys under "<name>:", only with read commands, and caps sizes so
a big key can't stall the server or the page.
"""
import socket

MAX_ITEMS = 100
MAX_BYTES = 4096
READ_CMDS = {"SCAN", "TYPE", "TTL", "GET", "STRLEN", "LRANGE", "LLEN", "SMEMBERS", "SCARD",
             "SSCAN", "HSCAN", "HLEN", "ZRANGE", "ZCARD", "XRANGE", "XLEN", "AUTH", "MEMORY"}


def _read(f):
    line = f.readline()
    if not line:
        raise ConnectionError("closed")
    t, rest = line[:1], line[1:-2]
    if t == b"+":
        return rest.decode()
    if t == b"-":
        raise ValueError(rest.decode(errors="replace"))
    if t == b":":
        return int(rest)
    if t == b"$":
        n = int(rest)
        return None if n < 0 else f.read(n + 2)[:-2]
    if t == b"*":
        n = int(rest)
        return None if n < 0 else [_read(f) for _ in range(n)]
    raise ValueError("unexpected reply")


class Conn:
    def __init__(self, host, port, user, password, timeout=5.0, sock=None):
        self.s = sock or socket.create_connection((host, port), timeout=timeout)
        self.f = self.s.makefile("rb")
        if password:
            self.cmd("AUTH", user, password)

    def cmd(self, *a):
        if str(a[0]).upper() not in READ_CMDS:
            raise PermissionError("browser is read-only")
        enc = [x if isinstance(x, bytes) else str(x).encode() for x in a]
        self.s.sendall(b"*%d\r\n" % len(enc) + b"".join(b"$%d\r\n%s\r\n" % (len(x), x) for x in enc))
        return _read(self.f)

    def close(self):
        self.f.close(); self.s.close()


def _txt(b):
    if b is None:
        return None
    t = b[:MAX_BYTES].decode("utf-8", errors="replace")
    return t + ("…" if len(b) > MAX_BYTES else "")


def scan(conn, name, cursor="0", pattern="*", count=MAX_ITEMS):
    if "\\" in pattern:
        raise ValueError("backslash not allowed in pattern")
    cur, keys = conn.cmd("SCAN", cursor, "MATCH", "%s:%s" % (name, pattern), "COUNT", min(int(count), 1000))
    return {"cursor": cur.decode() if isinstance(cur, bytes) else str(cur), "keys": [_txt(k) for k in keys]}


def show(conn, name, key):
    if not key.startswith(name + ":"):
        raise PermissionError("key outside this database")
    typ = conn.cmd("TYPE", key)
    out = {"key": key, "type": typ, "ttl": conn.cmd("TTL", key)}
    n = MAX_ITEMS - 1
    if typ == "none":
        return None
    if typ == "string":
        out["size"] = conn.cmd("STRLEN", key); out["value"] = _txt(conn.cmd("GET", key))
    elif typ == "list":
        out["size"] = conn.cmd("LLEN", key); out["value"] = [_txt(x) for x in conn.cmd("LRANGE", key, 0, n)]
    elif typ == "set":
        out["size"] = conn.cmd("SCARD", key); out["value"] = [_txt(x) for x in conn.cmd("SSCAN", key, 0, "COUNT", MAX_ITEMS)[1]]
    elif typ == "hash":
        out["size"] = conn.cmd("HLEN", key); r = conn.cmd("HSCAN", key, 0, "COUNT", MAX_ITEMS)[1]
        out["value"] = {_txt(r[i]): _txt(r[i + 1]) for i in range(0, len(r), 2)}
    elif typ == "zset":
        out["size"] = conn.cmd("ZCARD", key); r = conn.cmd("ZRANGE", key, 0, n, "WITHSCORES")
        out["value"] = [[_txt(r[i]), float(r[i + 1])] for i in range(0, len(r), 2)]
    elif typ == "stream":
        out["size"] = conn.cmd("XLEN", key); r = conn.cmd("XRANGE", key, "-", "+", "COUNT", MAX_ITEMS)
        out["value"] = [[_txt(e[0]), [_txt(x) for x in e[1]]] for e in r]
    else:
        out["value"] = None
    out["truncated"] = isinstance(out.get("size"), int) and out["size"] > MAX_ITEMS
    return out
