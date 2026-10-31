import threading
import time
import unittest
from edge_cache import EdgeCache


class T(unittest.TestCase):
    def setUp(self):
        self.now = [0.0]
        self.calls = []
        self.origin = {"a": b"1"}
        self.down = False

        def fetch(k):
            self.calls.append(k)
            if self.down:
                raise OSError("down")
            return self.origin.get(k)
        self.c = EdgeCache(fetch, ttl=5, stale=10, max_items=2, clock=lambda: self.now[0])

    def test_hit_then_refresh(self):
        self.assertEqual(self.c.get("a"), b"1")
        self.origin["a"] = b"2"
        self.assertEqual(self.c.get("a"), b"1")
        self.now[0] = 6
        self.assertEqual(self.c.get("a"), b"2")
        self.assertEqual(len(self.calls), 2)

    def test_stale_on_origin_error_then_give_up(self):
        self.c.get("a")
        self.down = True
        self.now[0] = 6
        self.assertEqual(self.c.get("a"), b"1")
        self.now[0] = 20
        with self.assertRaises(OSError):
            self.c.get("a")

    def test_invalidate_and_lru(self):
        self.c.get("a")
        self.origin["a"] = b"9"
        self.c.invalidate("a")
        self.assertEqual(self.c.get("a"), b"9")
        self.c.get("b")
        self.c.get("c")
        self.assertNotIn("a", self.c.items)

    def test_single_flight(self):
        gate = threading.Event()
        n = []

        def slow(k):
            n.append(k)
            gate.wait(2)
            return b"v"
        c = EdgeCache(slow)
        out = []
        ts = [threading.Thread(target=lambda: out.append(c.get("k"))) for _ in range(5)]
        for t in ts:
            t.start()
        time.sleep(0.1)
        gate.set()
        for t in ts:
            t.join()
        self.assertEqual(out, [b"v"] * 5)
        self.assertEqual(len(n), 1)


if __name__ == "__main__":
    unittest.main()
