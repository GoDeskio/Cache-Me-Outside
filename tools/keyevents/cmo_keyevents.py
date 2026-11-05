#!/usr/bin/env python3
"""Key-event webhooks (plan item 66): keyspace notifications -> signed HTTPS POSTs.

  CMO_EVENTS_URL=rediss://user:pass@host:6379/0
  CMO_EVENTS_WEBHOOK=https://example.com/hook      (https only)
  CMO_EVENTS_SECRET=...                            (HMAC-SHA256 signing key)
  CMO_EVENTS_KEYS='orders:*'                       (glob, default *)
  CMO_EVENTS_TYPES='set,del,expired,evicted'       (default)

The server must have notify-keyspace-events including E and the matching
classes (e.g. "Eg$x" for set/del/expired, add "e" for evicted). This tool does
not change server config. Pub/sub is fire-and-forget: events sent while the
tool is disconnected are lost, so treat webhooks as hints, not a ledger.
No third-party dependencies.
"""
import fnmatch
import hashlib
import hmac
import json
import os
import socket
import ssl
import sys
import time
import urllib.request
from urllib.parse import unquote, urlparse

DEFAULT_TYPES = ("set", "del", "expired", "evicted")


def sign(secret, body, ts):
    mac = hmac.new(secret.encode(), b"%d." % ts + body, hashlib.sha256).hexdigest()
    return "t=%d,v1=%s" % (ts, mac)


def verify(secret, body, header, now, tolerance=300):
    """Helper for receivers: constant-time check plus replay window."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        ts = int(parts["t"])
    except (ValueError, KeyError):
        return False
    if abs(now - ts) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, body, ts), header)


def to_event(channel, key, keys_glob, types):
    """channel like __keyevent@0__:set, payload = key name. None when filtered out."""
    if not channel.startswith("__keyevent@") or ":" not in channel:
        return None
    head, typ = channel.split(":", 1)
    if typ not in types or not fnmatch.fnmatchcase(key, keys_glob):
        return None
    db = head[len("__keyevent@"):].rstrip("_")
    return {"type": typ, "key": key, "db": int(db) if db.isdigit() else db}


class Sub:
    def __init__(self, url, timeout=None):
        u = urlparse(url)
        if u.scheme not in ("redis", "rediss"):
            raise ValueError("CMO_EVENTS_URL must be redis:// or rediss://")
        s = socket.create_connection((u.hostname or "127.0.0.1", u.port or 6379), timeout=10)
        s.settimeout(timeout)
        if u.scheme == "rediss":
            s = ssl.create_default_context().wrap_socket(s, server_hostname=u.hostname)
        self.s, self.f = s, s.makefile("rb")
        self.db = int((u.path or "/0").strip("/") or 0)
        if u.password:
            self.send("AUTH", *([unquote(u.username)] if u.username else []), unquote(u.password))
            r = self.read()
            if isinstance(r, Exception):
                raise r

    def send(self, *args):
        out = [b"*%d\r\n" % len(args)]
        for a in args:
            b = str(a).encode()
            out.append(b"$%d\r\n%s\r\n" % (len(b), b))
        self.s.sendall(b"".join(out))

    def read(self):
        line = self.f.readline()
        if not line:
            raise ConnectionError("closed")
        k, rest = line[:1], line[1:-2]
        if k == b"+":
            return rest.decode()
        if k == b"-":
            return RuntimeError(rest.decode())
        if k == b":":
            return int(rest)
        if k == b"$":
            n = int(rest)
            return None if n < 0 else self.f.read(n + 2)[:-2].decode("utf-8", "replace")
        if k == b"*":
            return [self.read() for _ in range(int(rest))]
        raise ConnectionError("bad reply")

    def events(self, types):
        self.send("SUBSCRIBE", *["__keyevent@%d__:%s" % (self.db, t) for t in types])
        while True:
            m = self.read()
            if isinstance(m, list) and len(m) == 3 and m[0] == "message":
                yield m[1], m[2]


def post(url, secret, event, opener=urllib.request.urlopen, tries=3, sleep=time.sleep):
    body = json.dumps(event, sort_keys=True).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-CMO-Signature": sign(secret, body, int(time.time())),
    })
    for i in range(tries):
        try:
            with opener(req, timeout=10) as r:
                if 200 <= r.status < 300:
                    return True
                if 400 <= r.status < 500 and r.status != 429:
                    return False
        except Exception:
            pass
        sleep(0.5 * 2 ** i)
    return False


def main():
    url, hook, secret = (os.environ.get(k, "") for k in ("CMO_EVENTS_URL", "CMO_EVENTS_WEBHOOK", "CMO_EVENTS_SECRET"))
    if not url or not hook.startswith("https://") or len(secret) < 16:
        print("need CMO_EVENTS_URL, an https CMO_EVENTS_WEBHOOK and CMO_EVENTS_SECRET (16+ chars)", file=sys.stderr)
        return 1
    glob = os.environ.get("CMO_EVENTS_KEYS", "*")
    types = tuple(t for t in os.environ.get("CMO_EVENTS_TYPES", ",".join(DEFAULT_TYPES)).split(",") if t)
    backoff = 1
    while True:
        try:
            for ch, key in Sub(url).events(types):
                backoff = 1
                ev = to_event(ch, key, glob, types)
                if ev and not post(hook, secret, ev):
                    print("webhook failed for %s %s" % (ev["type"], ev["key"]), file=sys.stderr)
        except (OSError, ConnectionError, RuntimeError) as e:
            print("disconnected (%s); retrying in %ds" % (e, backoff), file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    sys.exit(main())
