"""Loopback sidecar so another GoDesk app can call Cache Me Outside without linking a library.

  CMO_API=http://127.0.0.1:8088 CMO_ADMIN_TOKEN=... python3 integration/sidecar.py

Cache reads and writes need CMO_URL and CMO_PREFIX as well. Keys outside the
prefix are refused before a connection is opened. The process will not bind
a wildcard address.
"""
import json
import os
import socket
import sys

import cache_me_outside

MAX_VALUE = 65536
COMMANDS = {"GET", "SET", "DEL"}


def check_key(key, prefix):
    if not isinstance(key, str) or not prefix or not key.startswith(prefix):
        raise ValueError("key is outside the prefix")
    if len(key) > 512 or "\r" in key or "\n" in key or "\x00" in key:
        raise ValueError("key refused")
    return key


def _send(sock, args):
    enc = [a if isinstance(a, bytes) else str(a).encode() for a in args]
    sock.sendall(b"*%d\r\n" % len(enc) + b"".join(b"$%d\r\n%s\r\n" % (len(x), x) for x in enc))


def _read(stream):
    line = stream.readline()
    if not line:
        raise ConnectionError("closed")
    if line[:1] == b"-":
        raise RuntimeError(line[1:-2].decode(errors="replace"))
    if line[:1] == b"$":
        n = int(line[1:])
        if n < 0:
            return None
        return stream.read(n + 2)[:-2]
    if line[:1] == b"+":
        return line[1:-2]
    if line[:1] == b":":
        return int(line[1:])
    raise RuntimeError("unexpected reply")


def cache_call(url, prefix, args):
    from urllib.parse import urlsplit
    if args[0] not in COMMANDS:
        raise ValueError("command refused")
    check_key(args[1], prefix)
    if args[0] == "SET" and len(args) > 2 and len(str(args[2]).encode()) > MAX_VALUE:
        raise ValueError("value is too large")
    parts = urlsplit(url)
    if parts.scheme not in ("redis", "rediss", "valkey", "valkeys") or not parts.hostname:
        raise ValueError("CMO_URL must be a redis or valkey URL")
    if parts.scheme in ("rediss", "valkeys"):
        raise ValueError("the sidecar speaks plain TCP; terminate TLS in front of the cache")
    sock = socket.create_connection((parts.hostname, parts.port or 6379), 5)
    stream = sock.makefile("rb")
    try:
        if parts.password is not None:
            user = parts.username or "default"
            _send(sock, ["AUTH", user, parts.password])
            _read(stream)
        _send(sock, args)
        return _read(stream)
    finally:
        stream.close()
        sock.close()


def make_handler(client, cache_url, prefix):
    from http.server import BaseHTTPRequestHandler

    class H(BaseHTTPRequestHandler):
        server_version = "cmo-sidecar"

        def log_message(self, *a):
            pass

        def _send(self, status, obj):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_VALUE + 1024:
                raise ValueError("body too large")
            data = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("body must be an object")
            return data

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True, "version": cache_me_outside.version()})
            if self.path == "/v1/version":
                return self._send(200, {"name": "cache-me-outside", "version": cache_me_outside.version()})
            if self.path.split("?")[0].startswith("/v1/databases"):
                if client is None:
                    return self._send(503, {"error": "set CMO_API and CMO_ADMIN_TOKEN"})
                try:
                    self._send(200, client._call("GET", self.path))
                except RuntimeError as exc:
                    self._send(502, {"error": str(exc)})
                return
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                body = self._body()
                if path == "/v1/cache/get":
                    if not cache_url:
                        return self._send(503, {"error": "set CMO_URL and CMO_PREFIX"})
                    value = cache_call(cache_url, prefix, ["GET", body.get("key", "")])
                    shown = None if value is None else value.decode("utf-8", "replace")
                    return self._send(200, {"key": body.get("key"), "value": shown})
                if path == "/v1/cache/set":
                    if not cache_url:
                        return self._send(503, {"error": "set CMO_URL and CMO_PREFIX"})
                    args = ["SET", body.get("key", ""), body.get("value", "")]
                    if "ttl" in body:
                        ttl = body["ttl"]
                        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 1 or ttl > 8640000:
                            raise ValueError("ttl must be 1 to 8640000 seconds")
                        args.extend(["EX", ttl])
                    cache_call(cache_url, prefix, args)
                    return self._send(200, {"stored": True})
                if client and path == "/v1/databases":
                    return self._send(201, client.create_database(body.get("name", ""), **{
                        k: body[k] for k in ("max_conns", "ops_per_sec", "bytes_per_sec") if k in body}))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            except (OSError, RuntimeError) as exc:
                return self._send(502, {"error": str(exc)})
            self._send(404, {"error": "not found"})

    return H


def main(argv=None):
    import argparse
    from http.server import ThreadingHTTPServer
    ap = argparse.ArgumentParser(description="Cache Me Outside sidecar")
    ap.add_argument("--listen", default="127.0.0.1:8099")
    a = ap.parse_args(argv)
    host, _, port = a.listen.rpartition(":")
    if host not in ("127.0.0.1", "::1"):
        ap.error("the sidecar listens on 127.0.0.1 only")
    api = os.environ.get("CMO_API", "")
    token = os.environ.get("CMO_ADMIN_TOKEN", "")
    client = cache_me_outside.Client(api, token) if api and token else None
    srv = ThreadingHTTPServer((host, int(port)), make_handler(client, os.environ.get("CMO_URL", ""), os.environ.get("CMO_PREFIX", "")))
    print("sidecar on http://%s" % a.listen, file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
