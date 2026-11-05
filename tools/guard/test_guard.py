import unittest
import guard as g


class FakeR(dict):
    def set(self, k, v): self[k] = v


class T(unittest.TestCase):
    def test_rules(self):
        r = g.Rules([{"action": "allow", "cmd": "FLUSH*", "user": "admin"}, {"action": "deny", "cmd": "FLUSH*"},
                     {"action": "deny", "cmd": "DEL", "key": "billing:*"}])
        self.assertTrue(r.check("admin", "flushdb")[0]); self.assertFalse(r.check("app", "FLUSHALL")[0])
        self.assertFalse(r.check("app", "DEL", "billing:1")[0]); self.assertTrue(r.check("app", "DEL", "x")[0])

    def test_throttle_limiter_heartbeat(self):
        t = g.LagThrottler(1, 0.5)
        self.assertEqual(t.delay([0.2]), 0); self.assertEqual(t.delay([3]), 0.5); self.assertAlmostEqual(t.delay([1.5]), 0.25)
        l = g.UserLimiter(1, {"batch": 2})
        self.assertTrue(l.acquire("a")); self.assertFalse(l.acquire("a")); l.release("a"); self.assertTrue(l.acquire("a"))
        self.assertTrue(l.acquire("batch") and l.acquire("batch"))
        r = FakeR(); self.assertIsNone(g.heartbeat_lag(r))
        g.heartbeat_write(r, clock=lambda: 100.0); self.assertEqual(g.heartbeat_lag(r, clock=lambda: 102.5), 2.5)

    def test_queue(self):
        t = [0]
        q = g.Queue(visibility=10, max_deliveries=2, clock=lambda: t[0])
        a = q.push("a"); q.push("b")
        self.assertEqual(q.pull(), (a, "a")); self.assertTrue(q.ack(a)); self.assertFalse(q.ack(a))
        b = q.pull()[0]; self.assertIsNone(q.pull())
        t[0] = 11; self.assertEqual(q.pull()[0], b)   # redelivered
        t[0] = 22; self.assertIsNone(q.pull()); self.assertEqual(q.dead, [(b, "b")])


if __name__ == "__main__":
    unittest.main()
