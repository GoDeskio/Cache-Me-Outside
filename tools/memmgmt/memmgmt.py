"""Memory management helpers (plan #79, #81, #84, #85, #86). Independent rebuilds.

- rebalance(): move memory between tenant pools toward the best marginal hit gain (#79)
- WriteBudgetAdmission: admit items to flash only within a write-rate budget (#81)
- SizedCache: client near-cache bounded by bytes, not item count (#84)
- reaper_preset(): active-expire-effort / hz presets from the expiring-key share (#85)
- MemoryMonitor: free-memory pressure signal for autoscaling (#39) (#86)
"""
import sys
import time
from collections import OrderedDict


def rebalance(pools, step):
    """pools: {name: {"bytes": int, "marginal_hits": float, "min": int}}
    Move `step` bytes from the pool with the lowest marginal hits per byte to the highest."""
    eff = {n: p["marginal_hits"] / max(1, p["bytes"]) for n, p in pools.items()}
    give = [n for n in sorted(eff, key=eff.get) if pools[n]["bytes"] - step >= pools[n].get("min", 0)]
    take = max(eff, key=eff.get)
    if not give or give[0] == take:
        return None
    src = give[0]
    pools[src]["bytes"] -= step; pools[take]["bytes"] += step
    return {"from": src, "to": take, "bytes": step}


class WriteBudgetAdmission:
    """Token bucket of flash write bytes per second; small and hot items win under pressure."""

    def __init__(self, bytes_per_sec, burst=None, clock=time.monotonic):
        self.rate, self.cap = bytes_per_sec, burst or bytes_per_sec
        self.tokens, self.clock, self.t = self.cap, clock, clock()

    def admit(self, size, hits=0):
        now = self.clock(); self.tokens = min(self.cap, self.tokens + (now - self.t) * self.rate); self.t = now
        need = size if hits == 0 else size / (1 + hits)  # hot items cost less of the budget
        if need > self.tokens:
            return False
        self.tokens -= need
        return True


class SizedCache:
    def __init__(self, max_bytes, sizeof=lambda v: sys.getsizeof(v)):
        self.max, self.sizeof, self.d, self.used = max_bytes, sizeof, OrderedDict(), 0

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k); return self.d[k][0]
        return None

    def put(self, k, v):
        s = self.sizeof(v)
        if s > self.max:
            return False
        if k in self.d:
            self.used -= self.d.pop(k)[1]
        self.d[k] = (v, s); self.used += s
        while self.used > self.max:
            _, (_, os_) = self.d.popitem(last=False); self.used -= os_
        return True


def reaper_preset(expiring_share, expired_backlog_ratio):
    """Pick active-expire-effort (1-10) and hz from INFO-derived ratios."""
    if expired_backlog_ratio > 0.25 or expiring_share > 0.8:
        return {"active-expire-effort": 7, "hz": 50}
    if expired_backlog_ratio > 0.1 or expiring_share > 0.4:
        return {"active-expire-effort": 4, "hz": 20}
    return {"active-expire-effort": 1, "hz": 10}


class MemoryMonitor:
    """Hysteresis signal: 'scale-up' above high, 'scale-down' below low, else 'hold'."""

    def __init__(self, high=0.85, low=0.5, window=3):
        self.high, self.low, self.window, self.hist = high, low, window, []

    def observe(self, used, maxmem):
        self.hist = (self.hist + [used / maxmem if maxmem else 0])[-self.window:]
        if len(self.hist) < self.window:
            return "hold"
        if min(self.hist) > self.high:
            return "scale-up"
        if max(self.hist) < self.low:
            return "scale-down"
        return "hold"
