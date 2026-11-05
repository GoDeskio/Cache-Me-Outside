"""/v1/flow feed for the animated data-flow view (plan #130).

It turns two INFO snapshots into per-second rates for the path
request -> near cache -> hit | miss -> DB query, then serves them with flow.html.

  python3 flow_feed.py --redis 127.0.0.1:6379 --listen 127.0.0.1:8090
  python3 flow_feed.py --demo     # synthetic traffic, no server needed

Near-cache counters are optional (client-side tracking). Without them the near
tier is shown as a pass-through.
"""
import argparse
import json
import math
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'"


def flow(prev, cur, dt):
    def r(k):
        return max(0, int(cur.get(k, 0)) - int(prev.get(k, 0))) / dt if dt > 0 else 0.0
    near_hit, hit, miss = r("near_cache_hits"), r("keyspace_hits"), r("keyspace_misses")
    req = near_hit + hit + miss
    return {"req": round(req, 2), "near_hit": round(near_hit, 2), "cache_hit": round(hit, 2),
            "miss": round(miss, 2), "db": round(miss, 2),
            "hit_ratio": round((near_hit + hit) / req, 4) if req else None}


def info(host, port):
    s = socket.create_connection((host, port), 3)
    try:
        s.sendall(b"*1\r\n$4\r\nINFO\r\n")
        f = s.makefile("rb")
        n = int(f.readline()[1:])
        text = f.read(n).decode()
    finally:
        s.close()
    return dict(l.split(":", 1) for l in text.splitlines() if ":" in l and not l.startswith("#"))


def demo(t):
    base = 400 + 300 * math.sin(t / 7)
    return {"req": round(base, 2), "near_hit": round(base * .35, 2), "cache_hit": round(base * .5, 2),
            "miss": round(base * .15, 2), "db": round(base * .15, 2), "hit_ratio": 0.85}


class Source:
    def __init__(self, addr=None):
        self.addr, self.prev, self.t = addr, None, None

    def sample(self):
        now = time.monotonic()
        if not self.addr:
            return demo(now)
        h, p = self.addr.rsplit(":", 1)
        cur = info(h, int(p))
        out = flow(self.prev, cur, now - self.t) if self.prev else flow(cur, cur, 1)
        self.prev, self.t = cur, now
        return out


def make_handler(src):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def _send(self, body, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/flow":
                return self._send(json.dumps(src.sample()).encode(), "application/json")
            files = {"/": ("flow.html", "text/html"), "/flow.js": ("flow.js", "text/javascript")}
            if self.path not in files:
                self.send_error(404); return
            fn, ct = files[self.path]
            with open(os.path.join(HERE, fn), "rb") as f:
                self._send(f.read(), ct + "; charset=utf-8")
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redis"); ap.add_argument("--demo", action="store_true")
    ap.add_argument("--listen", default="127.0.0.1:8090")
    a = ap.parse_args()
    h, p = a.listen.rsplit(":", 1)
    ThreadingHTTPServer((h, int(p)), make_handler(Source(None if a.demo else a.redis))).serve_forever()


if __name__ == "__main__":
    main()
