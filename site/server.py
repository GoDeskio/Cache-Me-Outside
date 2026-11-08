"""Cache Me Outside site.

  python3 site/server.py --demo
  CMO_ADMIN_TOKEN=... python3 site/server.py --config proxy.json --server 127.0.0.1:6379

--demo listens on 127.0.0.1 only, keeps a sample key per database, and never
reads a token from the repository. The real mode uses CMO_ADMIN_TOKEN.
"""
import os
import secrets
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MGMT = os.path.normpath(os.path.join(HERE, "..", "tools", "mgmt"))
if MGMT not in sys.path:
    sys.path.insert(0, MGMT)

import cmo_mgmt as mgmt  # noqa: E402
from memstore import MemStore  # noqa: E402


class _Acl:
    def __init__(self):
        self.users = {}

    def set_user(self, name, password):
        self.users[name] = password

    def delete_user(self, name):
        self.users.pop(name, None)


class DemoManager(mgmt.Manager):
    def __init__(self, store):
        super().__init__(store, _Acl(), "127.0.0.1")
        self.demo = True
        self.mem = MemStore()
        self.browser_conn = self.mem.conn

    def create(self, body):
        out = super().create(body)
        with self.mem.lock:
            self.mem.data[out["name"] + ":welcome"] = b"hello from Cache Me Outside"
        out["sample_key"] = out["name"] + ":welcome"
        return out


def build(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Cache Me Outside site")
    ap.add_argument("--demo", action="store_true", help="loopback site with an in-memory database")
    ap.add_argument("--listen", default=None)
    ap.add_argument("--config")
    ap.add_argument("--server", default="127.0.0.1:6379")
    ap.add_argument("--proxy-bind", default="127.0.0.1")
    a = ap.parse_args(argv)
    if a.demo:
        listen = a.listen or "127.0.0.1:8088"
        host, _, port = listen.rpartition(":")
        if host not in ("127.0.0.1", "::1"):
            ap.error("demo mode listens on 127.0.0.1 only")
        token = secrets.token_urlsafe(24)
        directory = tempfile.mkdtemp(prefix="cmo-demo-")
        store = mgmt.Store(os.path.join(directory, "proxy.json"), "127.0.0.1:6379")
        mgr = DemoManager(store)
        return (host, int(port)), mgr, token, a
    token = os.environ.get("CMO_ADMIN_TOKEN", "")
    if len(token) < 24:
        ap.error("set CMO_ADMIN_TOKEN (24+ chars)")
    if not a.config:
        ap.error("--config is required unless --demo")
    listen = a.listen or "127.0.0.1:8088"
    host, _, port = listen.rpartition(":")
    if host in ("0.0.0.0", "::", "*"):
        ap.error("refusing a wildcard listen address; put TLS on a specific address")
    sh, _, sp = a.server.rpartition(":")
    acl = mgmt.Acl(sh, int(sp), os.environ.get("CMO_ADMIN_USER", "default"), os.environ.get("CMO_ADMIN_PASSWORD"))
    mgr = mgmt.Manager(mgmt.Store(a.config, a.server), acl, a.proxy_bind)
    return (host, int(port)), mgr, token, a


def main(argv=None):
    import http.server
    addr, mgr, token, _a = build(argv)
    srv = http.server.ThreadingHTTPServer(addr, mgmt.make_handler(mgr, token))
    where = "%s:%d" % addr
    if getattr(mgr, "demo", False):
        print("Cache Me Outside demo on http://%s (loopback only)" % where, file=sys.stderr)
    else:
        print("Cache Me Outside site on http://%s" % where, file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
