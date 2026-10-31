#!/usr/bin/env python3
"""HTTPS/REST command API for edge and serverless clients (plan item 45).

Rebuilt independently from public docs of the idea (send a Redis command over HTTP);
no third-party code. Standard library only.

  POST /            body: ["SET","k","v"]               -> {"result": "OK"}
  POST /pipeline    body: [["INCR","n"],["GET","n"]]     -> [{"result":1},{"result":"1"}]
  GET  /GET/k       path segments are the command        -> {"result": "v"}
  GET  /health                                           -> {"ok": true}

Auth: "Authorization: Bearer <api key>". The key is the ACL password of a
per-key Valkey user (item 63 keys), so ACL rules still decide what's allowed.
Format: "<user>:<password>" base64url, or the raw password for the default
user when CMO_REST_ALLOW_DEFAULT=1.

Blocked over HTTP (need a long-lived connection): SUBSCRIBE family, MONITOR,
BLPOP/BRPOP/BLMOVE/BZPOP*/XREAD BLOCK, and connection-state commands.

  CMO_UPSTREAM=127.0.0.1:6379 CMO_REST_LISTEN=127.0.0.1:8079 python3 cmo_rest.py
Put TLS in front (Caddy/Traefik); this listens on plain HTTP for the local hop.
"""
import base64
import binascii
import json
import os
import socket
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BLOCKED = {
    "SUBSCRIBE", "PSUBSCRIBE", "SSUBSCRIBE", "UNSUBSCRIBE", "PUNSUBSCRIBE", "SUNSUBSCRIBE",
    "MONITOR", "SYNC", "PSYNC", "REPLCONF", "BLPOP", "BRPOP", "BLMOVE", "BRPOPLPUSH",
    "BZPOPMIN", "BZPOPMAX", "BLMPOP", "BZMPOP", "AUTH", "HELLO", "SELECT", "RESET",
    "MULTI", "EXEC", "DISCARD", "WATCH", "UNWATCH", "CLIENT", "QUIT", "WAIT", "WAITAOF",
}
MAX_BODY = 1 << 20
MAX_PIPELINE = 100


class RespError(Exception):
    pass


def encode(args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a if isinstance(a, bytes) else str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class Reader:
    def __init__(self, sock):
        self.f = sock.makefile("rb")

    def line(self):
        s = self.f.readline()
        if not s.endswith(b"\r\n"):
            raise ConnectionError("upstream closed")
        return s[:-2]

    def read(self):
        s = self.line()
        t, rest = s[:1], s[1:]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            return RespError(rest.decode())
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n < 0:
                return None
            data = self.f.read(n + 2)[:-2]
            try:
                return data.decode()
            except UnicodeDecodeError:
                return {"base64": base64.b64encode(data).decode()}
        if t in (b"*", b"~", b">"):
            n = int(rest)
            return None if n < 0 else [self.read() for _ in range(n)]
        if t == b"%":
            n = int(rest)
            return {str(self.read()): self.read() for _ in range(n)}
        if t == b"_":
            return None
        if t == b"#":
            return rest == b"t"
        if t == b",":
            return float(rest)
        raise ConnectionError("unknown reply type %r" % t)


def check_command(cmd):
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, (str, int, float)) for x in cmd):
        return "Command must be a non-empty JSON array of strings or numbers."
    name = str(cmd[0]).upper()
    if name in BLOCKED:
        return "%s isn't available over HTTP." % name
    if name in ("XREAD", "XREADGROUP") and any(str(x).upper() == "BLOCK" for x in cmd):
        return "Blocking reads aren't available over HTTP."
    return None


def parse_key(header, allow_default):
    if not header.startswith("Bearer "):
        return None
    tok = header[7:].strip()
    try:
        raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4)).decode()
        if ":" in raw:
            user, pw = raw.split(":", 1)
            if user and pw:
                return user, pw
    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass
    return ("default", tok) if allow_default and tok else None


def to_json(v):
    if isinstance(v, RespError):
        return {"error": str(v)}
    if isinstance(v, list):
        return {"result": [to_json(x).get("result", to_json(x)) if not isinstance(x, RespError) else {"error": str(x)} for x in v]}
    return {"result": v}


def run(upstream, creds, commands, timeout=5.0):
    host, port = upstream.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        r = Reader(s)
        s.sendall(encode(["AUTH", creds[0], creds[1]]))
        a = r.read()
        if isinstance(a, RespError):
            raise PermissionError(str(a))
        s.sendall(b"".join(encode(c) for c in commands))
        return [r.read() for _ in commands]


class Handler(BaseHTTPRequestHandler):
    upstream = "127.0.0.1:6379"
    allow_default = False
    server_version = "cmo-rest"

    def log_message(self, *a):
        pass

    def send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_cmds(self, commands, single):
        creds = parse_key(self.headers.get("authorization", ""), self.allow_default)
        if not creds:
            return self.send(401, {"error": "Send Authorization: Bearer <api key>."})
        for c in commands:
            err = check_command(c)
            if err:
                return self.send(400, {"error": err})
        try:
            out = run(self.upstream, creds, commands)
        except PermissionError:
            return self.send(401, {"error": "API key not accepted."})
        except (OSError, ConnectionError):
            return self.send(502, {"error": "Database unreachable."})
        res = [to_json(x) for x in out]
        if single:
            return self.send(400 if "error" in res[0] else 200, res[0])
        return self.send(200, res)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/health":
            return self.send(200, {"ok": True})
        parts = [urllib.parse.unquote(p) for p in path.strip("/").split("/") if p]
        if not parts:
            return self.send(404, {"error": "Put the command in the path, e.g. /GET/key."})
        return self.handle_cmds([parts], True)

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        if n > MAX_BODY:
            return self.send(413, {"error": "Body too large."})
        try:
            body = json.loads(self.rfile.read(n) or b"null")
        except json.JSONDecodeError:
            return self.send(400, {"error": "Body must be JSON."})
        path = urllib.parse.urlsplit(self.path).path.rstrip("/")
        if path == "/pipeline":
            if not isinstance(body, list) or not body or len(body) > MAX_PIPELINE:
                return self.send(400, {"error": "Pipeline must be 1-%d commands." % MAX_PIPELINE})
            return self.handle_cmds(body, False)
        if path == "":
            return self.handle_cmds([body], True)
        return self.send(404, {"error": "Not found."})


def main():
    Handler.upstream = os.environ.get("CMO_UPSTREAM", "127.0.0.1:6379")
    Handler.allow_default = os.environ.get("CMO_REST_ALLOW_DEFAULT") == "1"
    host, port = os.environ.get("CMO_REST_LISTEN", "127.0.0.1:8079").rsplit(":", 1)
    ThreadingHTTPServer((host, int(port)), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
