"""Eviction simulator, trace-replay benchmark and policy presets (plan #78, #87, #103).

Independent rebuild from public descriptions of LRU, 2Q and TinyLFU (Einziger et al.).
  python3 evict_sim.py trace.txt --capacity 1000      # one key per line, or "key size"
It prints the hit ratio per policy and recommends a maxmemory-policy preset.
"""
import argparse
import hashlib
import json
import time
from collections import OrderedDict


class LRU:
    name = "lru"

    def __init__(self, cap):
        self.cap, self.d = cap, OrderedDict()

    def access(self, k):
        if k in self.d:
            self.d.move_to_end(k); return True
        self.d[k] = 1
        if len(self.d) > self.cap:
            self.d.popitem(last=False)
        return False


class TwoQ:
    """Simplified 2Q: A1in FIFO (25%), A1out ghost (50%), Am LRU."""
    name = "2q"

    def __init__(self, cap):
        self.kin = max(1, cap // 4); self.kout = max(1, cap // 2); self.cap = cap
        self.a1in, self.a1out, self.am = OrderedDict(), OrderedDict(), OrderedDict()

    def access(self, k):
        if k in self.am:
            self.am.move_to_end(k); return True
        if k in self.a1in:
            return True
        if k in self.a1out:
            del self.a1out[k]; self.am[k] = 1
            self._trim(); return False
        self.a1in[k] = 1; self._trim(); return False

    def _trim(self):
        while len(self.a1in) + len(self.am) > self.cap:
            if len(self.a1in) > self.kin or not self.am:
                old, _ = self.a1in.popitem(last=False)
                self.a1out[old] = 1
                if len(self.a1out) > self.kout:
                    self.a1out.popitem(last=False)
            else:
                self.am.popitem(last=False)


class CountMin:
    def __init__(self, width, depth=4):
        self.w, self.rows, self.n, self.reset_at = width, [[0] * width for _ in range(depth)], 0, width * 10

    def _idx(self, k):
        h = hashlib.blake2b(str(k).encode(), digest_size=16).digest()
        return [int.from_bytes(h[i * 4:i * 4 + 4], "little") % self.w for i in range(len(self.rows))]

    def add(self, k):
        for r, i in zip(self.rows, self._idx(k)):
            if r[i] < 15: r[i] += 1
        self.n += 1
        if self.n >= self.reset_at:  # aging
            self.rows = [[c // 2 for c in r] for r in self.rows]; self.n //= 2

    def est(self, k):
        return min(r[i] for r, i in zip(self.rows, self._idx(k)))


class TinyLFU(LRU):
    """LRU main cache guarded by a frequency-sketch admission filter."""
    name = "tinylfu"

    def __init__(self, cap):
        super().__init__(cap); self.sk = CountMin(max(16, cap * 4))

    def access(self, k):
        self.sk.add(k)
        if k in self.d:
            self.d.move_to_end(k); return True
        if len(self.d) < self.cap:
            self.d[k] = 1; return False
        victim = next(iter(self.d))
        if self.sk.est(k) > self.sk.est(victim):
            del self.d[victim]; self.d[k] = 1
        return False


POLICIES = [LRU, TwoQ, TinyLFU]
# Map a winning policy to the closest Valkey setting (#103 presets).
PRESETS = {
    "lru": {"maxmemory-policy": "allkeys-lru", "maxmemory-samples": 5},
    "2q": {"maxmemory-policy": "allkeys-lru", "maxmemory-samples": 10},
    "tinylfu": {"maxmemory-policy": "allkeys-lfu", "lfu-log-factor": 10, "lfu-decay-time": 1},
    "volatile-ttl": {"maxmemory-policy": "volatile-ttl"},
    "session-store": {"maxmemory-policy": "volatile-lru"},
    "no-evict": {"maxmemory-policy": "noeviction"},
}


def replay(trace, cap, policies=POLICIES):
    out = {}
    for P in policies:
        c, hits, t0 = P(cap), 0, time.perf_counter()
        for k in trace:
            hits += c.access(k)
        dt = time.perf_counter() - t0
        out[P.name] = {"hit_ratio": round(hits / len(trace), 4) if trace else 0.0,
                       "ns_per_op": round(dt * 1e9 / max(1, len(trace)))}
    return out


def recommend(results):
    best = max(results, key=lambda n: results[n]["hit_ratio"])
    return best, PRESETS[best]


def load(path):
    with open(path) as f:
        return [ln.split()[0] for ln in f if ln.strip()]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trace"); ap.add_argument("--capacity", type=int, default=1000)
    a = ap.parse_args()
    r = replay(load(a.trace), a.capacity); best, preset = recommend(r)
    print(json.dumps({"results": r, "best": best, "preset": preset}, indent=2))


if __name__ == "__main__":
    main()
