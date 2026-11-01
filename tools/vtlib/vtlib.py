"""Query consolidation, cost-sized cache, connection pool (plan #109-#111).
Independent rebuild of ideas seen in Vitess; stdlib only, no Vitess code.
"""
import collections
import threading
import time


class SingleFlight:
    """#109: concurrent identical calls share one execution and its result."""
    def __init__(self):
        self._lock, self._calls = threading.Lock(), {}
        self.consolidated = 0

    def do(self, key, fn):
        with self._lock:
            c = self._calls.get(key)
            if c:
                self.consolidated += 1
                leader = False
            else:
                c = self._calls[key] = {"ev": threading.Event(), "res": None, "err": None}
                leader = True
        if not leader:
            c["ev"].wait()
        else:
            try:
                c["res"] = fn()
            except Exception as e:  # noqa: BLE001
                c["err"] = e
            finally:
                with self._lock:
                    self._calls.pop(key, None)
                c["ev"].set()
        if c["err"]:
            raise c["err"]
        return c["res"]


class CostCache:
    """#110: LRU bounded by total cost (e.g. bytes), not entry count."""
    def __init__(self, capacity, cost=lambda v: len(v)):
        self.cap, self.costf, self.used = capacity, cost, 0
        self.d = collections.OrderedDict()
        self.evictions = 0

    def get(self, k):
        if k not in self.d:
            return None
        self.d.move_to_end(k)
        return self.d[k][0]

    def set(self, k, v):
        c = self.costf(v)
        if c > self.cap:
            return False
        if k in self.d:
            self.used -= self.d.pop(k)[1]
        self.d[k] = (v, c)
        self.used += c
        while self.used > self.cap:
            _, (_, oc) = self.d.popitem(last=False)
            self.used -= oc
            self.evictions += 1
        return True


class PoolTimeout(Exception):
    pass


class Pool:
    """#111: bounded pool, FIFO wait list, idle timeout, settings-aware reuse."""
    def __init__(self, factory, size, idle_timeout=300.0, clock=time.monotonic):
        self.factory, self.size, self.idle, self.clock = factory, size, idle_timeout, clock
        self.cv = threading.Condition()
        self.free = []          # [(conn, settings, last_used)]
        self.open = 0
        self.closed_idle = 0

    def _reap(self):
        now, keep = self.clock(), []
        for c, s, t in self.free:
            if now - t > self.idle:
                getattr(c, "close", lambda: None)()
                self.open -= 1; self.closed_idle += 1
            else:
                keep.append((c, s, t))
        self.free = keep

    def get(self, settings=None, timeout=1.0):
        deadline = time.monotonic() + timeout
        with self.cv:
            while True:
                self._reap()
                for i, (c, s, _) in enumerate(self.free):
                    if s == settings:
                        del self.free[i]
                        return c
                if self.free and self.open >= self.size:
                    c, _, _ = self.free.pop(0)
                    getattr(c, "close", lambda: None)()
                    self.open -= 1
                if self.open < self.size:
                    self.open += 1
                    c = self.factory(settings)
                    return c
                left = deadline - time.monotonic()
                if left <= 0:
                    raise PoolTimeout("pool exhausted")
                self.cv.wait(left)

    def put(self, conn, settings=None):
        with self.cv:
            self.free.append((conn, settings, self.clock()))
            self.cv.notify()
