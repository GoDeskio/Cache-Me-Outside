"""Operational cache routes (plan #94-#99). Independent rebuild; stdlib only.

Handles expose get/set/delete like tools/routes.
"""
import json
import random
import threading
import time


class Limited(Exception):
    pass


class RateLimit:
    """#94: token bucket per operation class; raises Limited when empty."""
    def __init__(self, child, rate, burst, clock=time.monotonic):
        self.c, self.rate, self.burst, self.clock = child, rate, burst, clock
        self.tokens, self.t = float(burst), clock()

    def _take(self):
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens < 1:
            raise Limited("rate limit")
        self.tokens -= 1

    def get(self, k): self._take(); return self.c.get(k)
    def set(self, k, v, ttl=None): self._take(); return self.c.set(k, v, ttl=ttl)
    def delete(self, k): self._take(); return self.c.delete(k)


class Outstanding:
    """#94: cap in-flight requests to a child."""
    def __init__(self, child, limit):
        self.c, self.sem = child, threading.BoundedSemaphore(limit)

    def _run(self, fn, *a, **kw):
        if not self.sem.acquire(blocking=False):
            raise Limited("too many outstanding")
        try:
            return fn(*a, **kw)
        finally:
            self.sem.release()

    def get(self, k): return self._run(self.c.get, k)
    def set(self, k, v, ttl=None): return self._run(self.c.set, k, v, ttl=ttl)
    def delete(self, k): return self._run(self.c.delete, k)


class Chaos:
    """#95: inject latency and errors for tests. Off unless enabled."""
    def __init__(self, child, delay_s=0.0, error_rate=0.0, rng=None, sleep=time.sleep):
        self.c, self.delay, self.err = child, delay_s, error_rate
        self.rng, self.sleep = rng or random.Random(), sleep

    def _pre(self):
        if self.delay:
            self.sleep(self.delay)
        if self.err and self.rng.random() < self.err:
            raise ConnectionError("injected fault")

    def get(self, k): self._pre(); return self.c.get(k)
    def set(self, k, v, ttl=None): self._pre(); return self.c.set(k, v, ttl=ttl)
    def delete(self, k): self._pre(); return self.c.delete(k)


class SizeSplit:
    """#96: small values in L1 (memory), large values in L2 (e.g. flash); L1 keeps a sentinel."""
    SENTINEL = "__cmo_l2__"

    def __init__(self, l1, l2, threshold):
        self.l1, self.l2, self.th = l1, l2, threshold

    def set(self, k, v, ttl=None):
        if len(v) > self.th:
            self.l2.set(k, v, ttl=ttl)
            return self.l1.set(k, self.SENTINEL, ttl=ttl)
        self.l2.delete(k)
        return self.l1.set(k, v, ttl=ttl)

    def get(self, k):
        v = self.l1.get(k)
        return self.l2.get(k) if v == self.SENTINEL else v

    def delete(self, k):
        self.l2.delete(k)
        return self.l1.delete(k)


class Rewrite:
    """#97: rewrite keys (prefix) and clamp/override TTLs."""
    def __init__(self, child, key_prefix="", max_ttl=None, force_ttl=None):
        self.c, self.p, self.max, self.force = child, key_prefix, max_ttl, force_ttl

    def _ttl(self, ttl):
        if self.force is not None:
            return self.force
        if self.max is not None:
            return self.max if ttl is None else min(ttl, self.max)
        return ttl

    def get(self, k): return self.c.get(self.p + k)
    def set(self, k, v, ttl=None): return self.c.set(self.p + k, v, ttl=self._ttl(ttl))
    def delete(self, k): return self.c.delete(self.p + k)


class AsyncLog:
    """#98: if a delete fails, append it to a JSONL log; replay() retries later."""
    def __init__(self, child, path):
        self.c, self.path = child, path

    def get(self, k): return self.c.get(k)
    def set(self, k, v, ttl=None): return self.c.set(k, v, ttl=ttl)

    def delete(self, k):
        try:
            return self.c.delete(k)
        except Exception:  # noqa: BLE001
            with open(self.path, "a") as f:
                f.write(json.dumps({"op": "delete", "key": k, "ts": time.time()}) + "\n")
            return False

    def replay(self):
        try:
            lines = open(self.path).read().splitlines()
        except FileNotFoundError:
            return 0
        left, done = [], 0
        for ln in lines:
            e = json.loads(ln)
            try:
                self.c.delete(e["key"]); done += 1
            except Exception:  # noqa: BLE001
                left.append(ln)
        with open(self.path, "w") as f:
            f.write("".join(x + "\n" for x in left))
        return done


class SlowWarmUp:
    """#99: send a growing share of traffic to a new host while its hit rate is low."""
    def __init__(self, new, fallback, min_hit=0.7, min_share=0.1, rng=None):
        self.new, self.fb, self.min_hit, self.min_share = new, fallback, min_hit, min_share
        self.hits = self.reqs = 0
        self.rng = rng or random.Random()

    def share(self):
        if self.reqs < 20:
            return self.min_share
        hr = self.hits / self.reqs
        return 1.0 if hr >= self.min_hit else max(self.min_share, hr / self.min_hit)

    def get(self, k):
        if self.rng.random() < self.share():
            v = self.new.get(k)
            self.reqs += 1
            if v is not None:
                self.hits += 1
                return v
            v = self.fb.get(k)
            if v is not None:
                self.new.set(k, v)
            return v
        return self.fb.get(k)

    def set(self, k, v, ttl=None):
        self.new.set(k, v, ttl=ttl)
        return self.fb.set(k, v, ttl=ttl)

    def delete(self, k):
        self.new.delete(k)
        return self.fb.delete(k)
