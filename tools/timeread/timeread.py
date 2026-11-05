"""Time-based reads and placement (plan #124-#127). Written from the Spanner paper only.

- HLC: hybrid logical clock with an uncertainty bound and commit wait (#124).
- pick_replica(): bounded-staleness / exact-timestamp read routing (#125).
- MVStore: lock-free snapshot reads at a timestamp (#126).
- Placement: key-prefix directories pinned to regions (#127).
"""
import bisect
import threading
import time


class HLC:
    def __init__(self, epsilon_ms=5, clock=lambda: time.time_ns() // 1_000_000, sleep=time.sleep):
        self.eps, self.clock, self.sleep = epsilon_ms, clock, sleep
        self.l, self.c, self.lock = 0, 0, threading.Lock()

    def now(self):
        with self.lock:
            pt = self.clock()
            if pt > self.l: self.l, self.c = pt, 0
            else: self.c += 1
            return (self.l, self.c)

    def update(self, remote):
        with self.lock:
            pt = self.clock(); rl, rc = remote; nl = max(self.l, rl, pt)
            if nl == self.l == rl: self.c = max(self.c, rc) + 1
            elif nl == self.l: self.c += 1
            elif nl == rl: self.c = rc + 1
            else: self.c = 0
            self.l = nl
            return (self.l, self.c)

    def interval(self):
        pt = self.clock(); return (pt - self.eps, pt + self.eps)

    def commit_wait(self, ts):
        """Block until `ts` is surely in the past on every node (earliest > ts)."""
        while self.interval()[0] <= ts[0]:
            self.sleep((ts[0] - self.interval()[0] + 1) / 1000)


def pick_replica(replicas, max_staleness_ms=None, at_ms=None, now_ms=None):
    """replicas: [{"name", "applied_ms", "local": bool}]. Prefer local replicas that are fresh enough."""
    now_ms = now_ms if now_ms is not None else time.time() * 1000
    need = at_ms if at_ms is not None else (now_ms - max_staleness_ms if max_staleness_ms is not None else now_ms)
    ok = [r for r in replicas if r["applied_ms"] >= need]
    if not ok: return None
    return sorted(ok, key=lambda r: (not r.get("local"), -r["applied_ms"]))[0]["name"]


class MVStore:
    def __init__(self):
        self.d = {}

    def write(self, k, ts, v):
        lst = self.d.setdefault(k, []); i = bisect.bisect(lst, (ts,)); lst.insert(i, (ts, v))

    def read(self, k, ts):
        lst = self.d.get(k, []); i = bisect.bisect_right(lst, (ts, chr(0x10FFFF))) - 1
        while i >= 0 and lst[i][0] > ts: i -= 1
        return lst[i][1] if i >= 0 else None

    def snapshot(self, ts, keys):
        return {k: self.read(k, ts) for k in keys}


class Placement:
    def __init__(self, rules, default):
        self.rules, self.default = sorted(rules.items(), key=lambda kv: -len(kv[0])), default

    def region(self, key):
        for p, r in self.rules:
            if key.startswith(p): return r
        return self.default

    def plan(self, current):
        """current: {key: region}. Returns keys to move."""
        return {k: self.region(k) for k, r in current.items() if r != self.region(k)}
