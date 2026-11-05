#!/usr/bin/env python3
"""Offline tests with an in-memory command fake (Lua scripts emulated by meaning)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from cmo_recipes import EXTEND, RELEASE, Leaderboard, Lock, RateLimiter, Sessions  # noqa: E402


class Fake:
    def __init__(self):
        self.kv, self.h, self.z, self.ttl = {}, {}, {}, {}

    def __call__(self, cmd, *a):
        c = cmd.upper()
        if c == "INCR":
            self.kv[a[0]] = str(int(self.kv.get(a[0], "0")) + 1); return int(self.kv[a[0]])
        if c in ("PEXPIRE", "EXPIRE"):
            hit = a[0] in self.kv or a[0] in self.h
            if hit: self.ttl[a[0]] = int(a[1])
            return int(hit)
        if c == "SET":
            if "NX" in a and a[0] in self.kv: return None
            self.kv[a[0]] = a[1]; return "OK"
        if c == "GET": return self.kv.get(a[0])
        if c == "DEL":
            return int(self.kv.pop(a[0], None) is not None or self.h.pop(a[0], None) is not None)
        if c == "EVAL":
            script, _, key, token = a[:4]
            if self.kv.get(key) != token: return 0
            if script == RELEASE: del self.kv[key]; return 1
            if script == EXTEND: self.ttl[key] = int(a[4]); return 1
        if c == "HSET":
            self.h.setdefault(a[0], {}).update(dict(zip(a[1::2], a[2::2]))); return 1
        if c == "HGETALL":
            return [x for kv in self.h.get(a[0], {}).items() for x in kv]
        if c == "ZINCRBY":
            z = self.z.setdefault(a[0], {}); z[a[2]] = z.get(a[2], 0) + float(a[1]); return str(z[a[2]])
        if c == "ZREVRANGE":
            items = sorted(self.z.get(a[0], {}).items(), key=lambda kv: -kv[1])[a[1]:a[2] + 1]
            return [x for m, s in items for x in (m, str(s))]
        if c == "ZREVRANK":
            order = [m for m, _ in sorted(self.z.get(a[0], {}).items(), key=lambda kv: -kv[1])]
            return order.index(a[1]) if a[1] in order else None
        raise AssertionError("unexpected " + c)


class T(unittest.TestCase):
    def test_rate_limit_window(self):
        f, now = Fake(), [100.0]
        rl = RateLimiter(f, "rl", 2, 10, clock=lambda: now[0])
        self.assertTrue(rl.hit("ip")["allowed"])
        self.assertEqual(rl.hit("ip")["remaining"], 0)
        self.assertFalse(rl.hit("ip")["allowed"])
        self.assertEqual(f.ttl["rl:ip:10"], 11000)
        now[0] = 110.0
        self.assertTrue(rl.hit("ip")["allowed"])

    def test_lock_owner_only(self):
        f = Fake()
        a, b = Lock(f, "job"), Lock(f, "job")
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        self.assertFalse(b.release())
        self.assertTrue(a.extend(5000)); self.assertEqual(f.ttl["lock:job"], 5000)
        self.assertTrue(a.release())
        with b:
            self.assertIn("lock:job", f.kv)
        self.assertNotIn("lock:job", f.kv)

    def test_lock_wait_times_out(self):
        f = Fake(); Lock(f, "x").acquire()
        self.assertFalse(Lock(f, "x").acquire(wait_s=0.01, retry_s=0.001))

    def test_sessions(self):
        f = Fake(); s = Sessions(f, idle_s=60)
        sid = s.create({"user": "u1"})
        self.assertEqual(s.get(sid), {"user": "u1"})
        self.assertEqual(f.ttl["sess:" + sid], 60)
        self.assertTrue(s.destroy(sid)); self.assertIsNone(s.get(sid))
        self.assertEqual(s.get(s.create({})), {})

    def test_leaderboard(self):
        f = Fake(); lb = Leaderboard(f, "g")
        lb.add("ann", 5); lb.add("bob", 7); lb.add("ann", 4)
        self.assertEqual(lb.top(2), [("ann", 9.0), ("bob", 7.0)])
        self.assertEqual(lb.rank("bob"), 2); self.assertIsNone(lb.rank("zed"))


if __name__ == "__main__":
    unittest.main()
