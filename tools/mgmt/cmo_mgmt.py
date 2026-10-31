"""Management REST API for Cache Me Outside (REA plan item 64).

Manages databases (tenants) for the per-tenant proxy (tools/proxy). Each
database gets:
  - an entry in the proxy config JSON (listen port + limits), and
  - an ACL user on the server limited to keys and channels "<name>:*".
Passwords are generated here, returned once, and never stored by this tool.

Endpoints (bearer token from env CMO_ADMIN_TOKEN, required):
  GET    /v1/databases
  POST   /v1/databases                  {"name", "port", "max_conns", "ops_per_sec", "bytes_per_sec"}
  GET    /v1/databases/{name}
  PATCH  /v1/databases/{name}           limits only
  DELETE /v1/databases/{name}
  POST   /v1/databases/{name}/rotate-password
  GET    /v1/openapi.json

The proxy reads its config at start, so restart it after changes.

  CMO_ADMIN_TOKEN=... CMO_ADMIN_PASSWORD=... python3 cmo_mgmt.py \
      --config proxy.json --server 127.0.0.1:6379 --listen 127.0.0.1:8088
Standard library only.
"""
import argparse
import hmac
import http.server
import json
import os
import re
import secrets
import socket
import tempfile
import threading

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
LIMITS = ("max_conns", "ops_per_sec", "bytes_per_sec")
PORT_MIN, PORT_MAX = 7001, 7999


class ApiError(Exception):
    def __init__(self, status, msg):
        super().__init__(msg)
        self.status = status


class Acl:
    """Talks ACL commands to the server over plain RESP2."""
    def __init__(self, host, port, user="default", password=None, timeout=5.0):
        self.addr, self.user, self.password, self.timeout = (host, port), user, password, timeout

    def _cmd(self, *args):
        with socket.create_connection(self.addr, timeout=self.timeout) as s, s.makefile("rb") as f:
            def send(*a):
                s.sendall(b"*%d\r\n" % len(a) + b"".join(
                    b"$%d\r\n%s\r\n" % (len(x.encode()), x.encode()) for x in a))
                line = f.readline()
                if line[:1] == b"-":
                    raise ApiError(502, "server: " + line[1:-2].decode(errors="replace"))
                if line[:1] == b"$" and int(line[1:-2]) >= 0:
                    f.read(int(line[1:-2]) + 2)
                return line
            if self.password:
                send("AUTH", self.user, self.password)
            return send(*args)

    def set_user(self, name, password):
        self._cmd("ACL", "SETUSER", name, "reset", "on", ">" + password,
                  "~%s:*" % name, "&%s:*" % name, "+@all", "-@admin", "-@dangerous")
        self._save()

    def delete_user(self, name):
        self._cmd("ACL", "DELUSER", name)
        self._save()

    def _save(self):
        try:
            self._cmd("ACL", "SAVE")
        except ApiError:
            pass  # no aclfile configured; ACLs live until restart


class Store:
    def __init__(self, path, upstream):
        self.path, self.upstream = path, upstream
        self.lock = threading.Lock()

    def read(self):
        if not os.path.exists(self.path):
            return {"tenants": {}}
        with open(self.path) as f:
            return json.load(f)

    def write(self, cfg):
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".cmo-mgmt-")
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)


def _limits(body, required=False):
    out = {}
    for k in LIMITS:
        if k in body:
            v = body[k]
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise ApiError(400, "%s must be a non-negative integer" % k)
            out[k] = v
    return out


def public(name, t):
    return {"name": name, "port": int(t["listen"].rpartition(":")[2]),
            **{k: t.get(k, 0) for k in LIMITS}}


class Manager:
    def __init__(self, store, acl, bind_host="0.0.0.0"):
        self.store, self.acl, self.bind_host = store, acl, bind_host

    def list(self):
        cfg = self.store.read()
        return [public(n, t) for n, t in sorted(cfg["tenants"].items())]

    def get(self, name):
        t = self.store.read()["tenants"].get(name)
        if not t:
            raise ApiError(404, "no such database")
        return public(name, t)

    def create(self, body):
        name = body.get("name", "")
        if not isinstance(name, str) or not NAME_RE.match(name) or name == "default":
            raise ApiError(400, "name: 2-31 chars, lowercase letters, digits, dashes, starting with a letter")
        limits = _limits(body)
        with self.store.lock:
            cfg = self.store.read()
            if name in cfg["tenants"]:
                raise ApiError(409, "database exists")
            used = {int(t["listen"].rpartition(":")[2]) for t in cfg["tenants"].values()}
            port = body.get("port")
            if port is None:
                port = next((p for p in range(PORT_MIN, PORT_MAX + 1) if p not in used), None)
                if port is None:
                    raise ApiError(409, "no free ports")
            elif not isinstance(port, int) or not PORT_MIN <= port <= PORT_MAX or port in used:
                raise ApiError(400, "port must be a free port in %d-%d" % (PORT_MIN, PORT_MAX))
            password = secrets.token_urlsafe(24)
            self.acl.set_user(name, password)
            cfg["tenants"][name] = {"listen": "%s:%d" % (self.bind_host, port),
                                    "upstream": self.store.upstream, **limits}
            self.store.write(cfg)
        out = public(name, cfg["tenants"][name])
        out["password"] = password
        out["note"] = "Shown once. Keys and channels must start with '%s:'. Restart the proxy to apply." % name
        return out

    def update(self, name, body):
        limits = _limits(body)
        if not limits:
            raise ApiError(400, "nothing to change")
        with self.store.lock:
            cfg = self.store.read()
            if name not in cfg["tenants"]:
                raise ApiError(404, "no such database")
            cfg["tenants"][name].update(limits)
            self.store.write(cfg)
            return public(name, cfg["tenants"][name])

    def delete(self, name):
        with self.store.lock:
            cfg = self.store.read()
            if name not in cfg["tenants"]:
                raise ApiError(404, "no such database")
            self.acl.delete_user(name)
            del cfg["tenants"][name]
            self.store.write(cfg)
        return {"deleted": name, "note": "Keys under '%s:' are not removed." % name}

    def rotate(self, name):
        self.get(name)
        password = secrets.token_urlsafe(24)
        self.acl.set_user(name, password)
        return {"name": name, "password": password, "note": "Shown once. Old password stops working now."}


OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Cache Me Outside management API", "version": "1"},
    "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
                   "schemas": {"Limits": {"type": "object", "properties": {
                       k: {"type": "integer", "minimum": 0} for k in LIMITS}}}},
    "security": [{"bearer": []}],
    "paths": {
        "/v1/databases": {"get": {"summary": "List databases"},
                          "post": {"summary": "Create a database; returns its password once"}},
        "/v1/databases/{name}": {"get": {"summary": "Get one"}, "patch": {"summary": "Change limits"},
                                 "delete": {"summary": "Delete (keys are kept)"}},
        "/v1/databases/{name}/rotate-password": {"post": {"summary": "New password, returned once"}},
    },
}


def make_handler(mgr, token):
    class H(http.server.BaseHTTPRequestHandler):
        server_version = "cmo-mgmt"

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
            if n > 65536:
                raise ApiError(413, "body too large")
            try:
                b = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ApiError(400, "invalid JSON")
            if not isinstance(b, dict):
                raise ApiError(400, "body must be an object")
            return b

        def _route(self, method):
            try:
                auth = self.headers.get("Authorization", "")
                if not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
                    raise ApiError(401, "unauthorized")
                p = self.path.split("?")[0].rstrip("/")
                parts = p.split("/")[1:]
                if p == "/v1/openapi.json" and method == "GET":
                    return self._send(200, OPENAPI)
                if parts[:2] != ["v1", "databases"]:
                    raise ApiError(404, "not found")
                if len(parts) == 2:
                    if method == "GET":
                        return self._send(200, {"databases": mgr.list()})
                    if method == "POST":
                        return self._send(201, mgr.create(self._body()))
                elif len(parts) == 3:
                    n = parts[2]
                    if method == "GET":
                        return self._send(200, mgr.get(n))
                    if method == "PATCH":
                        return self._send(200, mgr.update(n, self._body()))
                    if method == "DELETE":
                        return self._send(200, mgr.delete(n))
                elif len(parts) == 4 and parts[3] == "rotate-password" and method == "POST":
                    return self._send(200, mgr.rotate(parts[2]))
                raise ApiError(405 if len(parts) <= 4 else 404, "method not allowed")
            except ApiError as e:
                self._send(e.status, {"error": str(e)})
            except OSError:
                self._send(502, {"error": "server unreachable"})

        def do_GET(self): self._route("GET")
        def do_POST(self): self._route("POST")
        def do_PATCH(self): self._route("PATCH")
        def do_DELETE(self): self._route("DELETE")

    return H


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, help="proxy config JSON")
    ap.add_argument("--server", default="127.0.0.1:6379")
    ap.add_argument("--listen", default="127.0.0.1:8088")
    ap.add_argument("--proxy-bind", default="0.0.0.0")
    a = ap.parse_args(argv)
    token = os.environ.get("CMO_ADMIN_TOKEN", "")
    if len(token) < 24:
        ap.error("set CMO_ADMIN_TOKEN (24+ chars)")
    sh, _, sp = a.server.rpartition(":")
    acl = Acl(sh, int(sp), os.environ.get("CMO_ADMIN_USER", "default"), os.environ.get("CMO_ADMIN_PASSWORD"))
    mgr = Manager(Store(a.config, a.server), acl, a.proxy_bind)
    lh, _, lp = a.listen.rpartition(":")
    srv = http.server.ThreadingHTTPServer((lh, int(lp)), make_handler(mgr, token))
    print("cmo-mgmt listening on %s (put TLS in front if not localhost)" % a.listen)
    srv.serve_forever()


if __name__ == "__main__":
    main()
