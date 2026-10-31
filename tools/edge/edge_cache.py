#!/usr/bin/env python3
"""Edge read cache for global reads (plan item 46). Built from scratch.

An edge node keeps a bounded LRU of recent reads and serves them for `ttl`
seconds (eventual consistency). After that it may serve the stale value for
`stale` more seconds while one background-style refresh happens; concurrent
misses for the same key share one origin fetch. Writes go to the origin and
publish an invalidation; edges call `invalidate(key)` when they see it
(e.g. from a Valkey pub/sub channel `cmo:inval`).

`fetch(key) -> bytes | None` is the origin read (REST API #45 or a RESP client).
"""
import threading
import time
from collections import OrderedDict


class EdgeCache:
    def __init__(self, fetch, ttl=5.0, stale=30.0, max_items=10000, clock=time.monotonic):
        self.fetch, self.ttl, self.stale, self.max = fetch, ttl, stale, max_items
        self.clock = clock
        self.items = OrderedDict()  # key -> (value, fetched_at)
        self.lock = threading.Lock()
        self.inflight = {}
        self.stats = {"hit": 0, "stale": 0, "miss": 0, "origin_error": 0}

    def _put(self, key, value):
        self.items[key] = (value, self.clock())
        self.items.move_to_end(key)
        while len(self.items) > self.max:
            self.items.popitem(last=False)

    def _load(self, key):
        with self.lock:
            ev = self.inflight.get(key)
            leader = ev is None
            if leader:
                ev = self.inflight[key] = threading.Event()
        if not leader:
            ev.wait(10)
            with self.lock:
                hit = self.items.get(key)
            return hit[0] if hit else None
        try:
            v = self.fetch(key)
            with self.lock:
                self._put(key, v)
            return v
        finally:
            with self.lock:
                self.inflight.pop(key, None)
            ev.set()

    def get(self, key):
        now = self.clock()
        with self.lock:
            hit = self.items.get(key)
            if hit:
                self.items.move_to_end(key)
        if hit:
            age = now - hit[1]
            if age < self.ttl:
                self.stats["hit"] += 1
                return hit[0]
            if age < self.ttl + self.stale:
                self.stats["stale"] += 1
                try:
                    return self._load(key)
                except Exception:
                    self.stats["origin_error"] += 1
                    return hit[0]  # origin down: keep serving stale inside the window
        self.stats["miss"] += 1
        return self._load(key)

    def invalidate(self, key):
        with self.lock:
            self.items.pop(key, None)
