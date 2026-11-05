"""Bloom filter, sampled command log, request spans (plan #101, #102, #108). Independent rebuilds.

- Bloom: client-side filter sized from (n, p); the server-side type ships as valkey-bloom
  (BSD-3, BF.* commands). Use this one for edge pre-checks or tests.
- klog(): parse MONITOR lines, keep a 1-in-N sample, redact values (#102).
- Span/Tracer: OTLP/JSON-shaped spans for cache calls (#108), exported with #40.
"""
import hashlib
import math
import os
import random
import re
import time


class Bloom:
    def __init__(self, n, p=0.01):
        self.m = max(8, int(-n * math.log(p) / (math.log(2) ** 2)))
        self.k = max(1, round(self.m / n * math.log(2)))
        self.bits = bytearray((self.m + 7) // 8)

    def _h(self, item):
        d = hashlib.sha256(str(item).encode()).digest()
        a, b = int.from_bytes(d[:8], "little"), int.from_bytes(d[8:16], "little") | 1
        return [(a + i * b) % self.m for i in range(self.k)]

    def add(self, item):
        for i in self._h(item): self.bits[i >> 3] |= 1 << (i & 7)

    def __contains__(self, item):
        return all(self.bits[i >> 3] >> (i & 7) & 1 for i in self._h(item))


MON = re.compile(r'^(?P<ts>[\d.]+) \[(?P<db>\d+) (?P<client>[^\]]+)\] (?P<args>.*)$')
WRITE_VALUE_ARGS = {"SET": 2, "SETEX": 3, "PSETEX": 3, "APPEND": 2, "GETSET": 2, "HSET": None, "LPUSH": None,
                    "RPUSH": None, "SADD": None, "PUBLISH": 2, "AUTH": 1, "HELLO": None, "MIGRATE": None, "CONFIG": None}


def redact(args):
    if not args:
        return args
    c = args[0].upper(); keep = WRITE_VALUE_ARGS.get(c, -1)
    if keep == -1:
        return args
    if keep is None:  # keep command + first key only
        return args[:2] + ["<redacted>"] * (len(args) > 2)
    return [("<redacted>" if i >= keep else a) for i, a in enumerate(args)]


def klog(lines, every=100, rng=None):
    rng = rng or random.Random()
    for ln in lines:
        m = MON.match(ln.strip())
        if not m or rng.random() * every >= 1:
            continue
        args = re.findall(r'"((?:[^"\\]|\\.)*)"', m["args"])
        yield {"ts": float(m["ts"]), "client": m["client"].split(":")[0], "cmd": redact(args)}


class Tracer:
    def __init__(self, service="cmo-client"):
        self.service, self.spans = service, []

    def span(self, name, **attrs):
        tr = self

        class S:
            def __enter__(s):
                s.t0 = time.time_ns(); return s

            def __exit__(s, et, ev, tb):
                tr.spans.append({"traceId": os.urandom(16).hex(), "spanId": os.urandom(8).hex(), "name": name,
                                 "startTimeUnixNano": s.t0, "endTimeUnixNano": time.time_ns(),
                                 "attributes": [{"key": k, "value": {"stringValue": str(v)}} for k, v in attrs.items()],
                                 "status": {"code": 2 if et else 1}})
                return False
        return S()

    def otlp(self):
        return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": self.service}}]},
                                   "scopeSpans": [{"scope": {"name": "cmo"}, "spans": self.spans}]}]}
