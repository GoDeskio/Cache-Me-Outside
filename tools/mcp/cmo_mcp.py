#!/usr/bin/env python3
"""Cache Me Outside MCP server (plan item 72): lets AI agents use a cache.

Stdio JSON-RPC (Model Context Protocol), no third-party dependencies.
Connect with CMO_MCP_URL=redis://user:pass@host:6379/0 (rediss:// for TLS).
Read-only by default; set CMO_MCP_WRITE=1 to expose cache_set/cache_delete.
Use a per-agent ACL user or a scoped API key (deploy/api-key.sh) so the
server can only touch the key prefix you intend.
"""
import json
import os
import socket
import ssl
import sys
from urllib.parse import unquote, urlparse

PROTOCOL = "2025-06-18"
MAX_VALUE = 64 * 1024


class RespError(Exception):
    pass


class Resp:
    """Minimal RESP2 client: enough for the commands below."""

    def __init__(self, url, timeout=5.0):
        u = urlparse(url)
        if u.scheme not in ("redis", "rediss"):
            raise ValueError("CMO_MCP_URL must start with redis:// or rediss://")
        sock = socket.create_connection((u.hostname or "127.0.0.1", u.port or 6379), timeout=timeout)
        if u.scheme == "rediss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
        self.sock = sock
        self.buf = sock.makefile("rb")
        if u.password:
            self.call("AUTH", *( [unquote(u.username)] if u.username else [] ), unquote(u.password))
        db = (u.path or "/").strip("/")
        if db and db != "0":
            self.call("SELECT", db)

    def call(self, *args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            b = a if isinstance(a, bytes) else str(a).encode()
            out.append(b"$%d\r\n%s\r\n" % (len(b), b))
        self.sock.sendall(b"".join(out))
        return self._read()

    def _read(self):
        line = self.buf.readline()
        if not line:
            raise RespError("connection closed")
        kind, rest = line[:1], line[1:-2]
        if kind == b"+":
            return rest.decode()
        if kind == b"-":
            raise RespError(rest.decode())
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n < 0:
                return None
            data = self.buf.read(n + 2)[:-2]
            return data.decode("utf-8", "replace")
        if kind == b"*":
            n = int(rest)
            return None if n < 0 else [self._read() for _ in range(n)]
        raise RespError("unexpected reply")


def _schema(props, required):
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


KEY = {"type": "string", "minLength": 1, "maxLength": 512}
READ_TOOLS = [
    {"name": "cache_get", "description": "Read a string value by key.", "inputSchema": _schema({"key": KEY}, ["key"])},
    {"name": "cache_ttl", "description": "Seconds until a key expires (-1 no expiry, -2 missing).", "inputSchema": _schema({"key": KEY}, ["key"])},
    {"name": "cache_scan", "description": "List up to `limit` keys matching a glob pattern (SCAN, non-blocking).",
     "inputSchema": _schema({"pattern": {"type": "string", "maxLength": 256}, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, [])},
    {"name": "cache_stats", "description": "Hit rate, memory and ops/s for this cache.", "inputSchema": _schema({}, [])},
]
WRITE_TOOLS = [
    {"name": "cache_set", "description": "Store a string value, optionally with a TTL in seconds.",
     "inputSchema": _schema({"key": KEY, "value": {"type": "string", "maxLength": MAX_VALUE}, "ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 31536000}}, ["key", "value"])},
    {"name": "cache_delete", "description": "Delete one key.", "inputSchema": _schema({"key": KEY}, ["key"])},
]


def stats_from_info(text):
    v = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith("#"):
            k, _, val = line.partition(":")
            v[k.strip()] = val.strip()
    hits, misses = int(v.get("keyspace_hits", 0)), int(v.get("keyspace_misses", 0))
    used, cap = int(v.get("used_memory", 0)), int(v.get("maxmemory", 0))
    return {
        "hit_rate": round(hits / (hits + misses), 4) if hits + misses else None,
        "used_memory": used,
        "maxmemory": cap,
        "memory_ratio": round(used / cap, 4) if cap else None,
        "ops_per_sec": int(v.get("instantaneous_ops_per_sec", 0)),
        "connected_clients": int(v.get("connected_clients", 0)),
        "evicted_keys": int(v.get("evicted_keys", 0)),
    }


class Server:
    def __init__(self, connect, write=False):
        self.connect = connect
        self.write = write
        self.conn = None

    def client(self):
        if self.conn is None:
            self.conn = self.connect()
        return self.conn

    def tools(self):
        return READ_TOOLS + (WRITE_TOOLS if self.write else [])

    def run_tool(self, name, args):
        if name not in {t["name"] for t in self.tools()}:
            raise ValueError("unknown or disabled tool: %s" % name)
        c = self.client()
        if name == "cache_get":
            return {"key": args["key"], "value": c.call("GET", args["key"])}
        if name == "cache_ttl":
            return {"key": args["key"], "ttl": c.call("TTL", args["key"])}
        if name == "cache_scan":
            pattern, limit = args.get("pattern") or "*", int(args.get("limit") or 50)
            cursor, keys = "0", []
            for _ in range(100):
                cursor, batch = c.call("SCAN", cursor, "MATCH", pattern, "COUNT", 100)
                keys.extend(batch)
                if cursor == "0" or len(keys) >= limit:
                    break
            return {"keys": keys[:limit], "truncated": len(keys) > limit or cursor != "0"}
        if name == "cache_stats":
            return stats_from_info(c.call("INFO", "everything"))
        if name == "cache_set":
            value = args["value"]
            if len(value.encode()) > MAX_VALUE:
                raise ValueError("value too large")
            extra = ["EX", int(args["ttl_seconds"])] if args.get("ttl_seconds") else []
            return {"key": args["key"], "result": c.call("SET", args["key"], value, *extra)}
        if name == "cache_delete":
            return {"key": args["key"], "deleted": c.call("DEL", args["key"])}
        raise ValueError(name)

    def handle(self, msg):
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None  # notification
        try:
            if method == "initialize":
                result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "cache-me-outside", "version": "0.1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": self.tools()}
            elif method == "tools/call":
                p = msg.get("params") or {}
                try:
                    data = self.run_tool(p.get("name"), p.get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": False}
                except (RespError, ValueError, KeyError, OSError) as e:
                    if isinstance(e, OSError):
                        self.conn = None
                    result = {"content": [{"type": "text", "text": "error: %s" % e}], "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as e:  # never crash the stdio loop
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def main():
    url = os.environ.get("CMO_MCP_URL", "redis://127.0.0.1:6379/0")
    server = Server(lambda: Resp(url), write=os.environ.get("CMO_MCP_WRITE") == "1")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = server.handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
