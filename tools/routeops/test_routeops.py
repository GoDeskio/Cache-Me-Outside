import os
import random
import tempfile
import unittest
from routeops import RateLimit, Outstanding, Chaos, SizeSplit, Rewrite, AsyncLog, SlowWarmUp, Limited


class Mem:
    def __init__(self, fail=False):
        self.d, self.fail, self.ttls = {}, fail, {}

    def get(self, k):
        if self.fail: raise ConnectionError
        return self.d.get(k)

    def set(self, k, v, ttl=None):
        if self.fail: raise ConnectionError
        self.d[k] = v; self.ttls[k] = ttl; return True

    def delete(self, k):
        if self.fail: raise ConnectionError
        return self.d.pop(k, None) is not None


class T(unittest.TestCase):
    def test_rate_limit(self):
        t = [0.0]
        r = RateLimit(Mem(), rate=1, burst=2, clock=lambda: t[0])
        r.get("a"); r.get("a")
        with self.assertRaises(Limited):
            r.get("a")
        t[0] = 1.0
        r.get("a")

    def test_outstanding(self):
        o = Outstanding(Mem(), 1)
        o.sem.acquire()
        with self.assertRaises(Limited):
            o.get("a")

    def test_chaos(self):
        slept = []
        c = Chaos(Mem(), delay_s=0.5, error_rate=1.0, sleep=slept.append)
        with self.assertRaises(ConnectionError):
            c.get("a")
        self.assertEqual(slept, [0.5])

    def test_size_split(self):
        l1, l2 = Mem(), Mem()
        s = SizeSplit(l1, l2, 4)
        s.set("big", "x" * 10); s.set("small", "x")
        self.assertEqual(s.get("big"), "x" * 10)
        self.assertNotIn("small", l2.d)
        s.set("big", "y")
        self.assertNotIn("big", l2.d)

    def test_rewrite(self):
        m = Mem()
        r = Rewrite(m, key_prefix="t1:", max_ttl=60)
        r.set("a", 1, ttl=600); r.set("b", 1)
        self.assertEqual((m.ttls["t1:a"], m.ttls["t1:b"]), (60, 60))

    def test_async_log(self):
        p = os.path.join(tempfile.mkdtemp(), "log.jsonl")
        m = Mem(); m.d["k"] = 1; m.fail = True
        a = AsyncLog(m, p)
        self.assertFalse(a.delete("k"))
        m.fail = False
        self.assertEqual(a.replay(), 1)
        self.assertNotIn("k", m.d)
        self.assertEqual(open(p).read(), "")

    def test_slow_warmup(self):
        new, fb = Mem(), Mem()
        for i in range(100): fb.d[i] = i
        s = SlowWarmUp(new, fb, rng=random.Random(1))
        self.assertEqual(s.share(), 0.1)
        for _ in range(5):
            for i in range(100): self.assertEqual(s.get(i), i)
        self.assertGreater(s.share(), 0.1)


if __name__ == "__main__":
    unittest.main()
