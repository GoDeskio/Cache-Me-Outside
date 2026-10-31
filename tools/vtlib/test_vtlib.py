import threading
import time
import unittest
from vtlib import SingleFlight, CostCache, Pool, PoolTimeout


class T(unittest.TestCase):
    def test_singleflight(self):
        sf, calls = SingleFlight(), []
        gate = threading.Event()

        def slow():
            calls.append(1); gate.wait(1); return 42
        res = []
        ts = [threading.Thread(target=lambda: res.append(sf.do("q", slow))) for _ in range(5)]
        for t in ts: t.start()
        time.sleep(0.1); gate.set()
        for t in ts: t.join()
        self.assertEqual((len(calls), res), (1, [42] * 5))
        self.assertEqual(sf.consolidated, 4)

    def test_singleflight_error(self):
        with self.assertRaises(ZeroDivisionError):
            SingleFlight().do("x", lambda: 1 / 0)

    def test_cost_cache(self):
        c = CostCache(10)
        c.set("a", "xxxx"); c.set("b", "xxxx"); c.get("a"); c.set("c", "xxxx")
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.get("a"), "xxxx")
        self.assertFalse(c.set("huge", "x" * 11))
        self.assertLessEqual(c.used, 10)

    def test_pool(self):
        t = [0.0]
        made = []
        p = Pool(lambda s: made.append(s) or object(), 2, idle_timeout=10, clock=lambda: t[0])
        a = p.get("utf8"); b = p.get(None)
        with self.assertRaises(PoolTimeout):
            p.get(timeout=0.05)
        p.put(a, "utf8")
        self.assertIs(p.get("utf8"), a)
        p.put(a, "utf8")
        p.get("latin1")  # different settings: recycle
        self.assertEqual(made, ["utf8", None, "latin1"])
        p.put(b); t[0] = 100
        p.get(None)
        self.assertEqual(p.closed_idle, 1)


if __name__ == "__main__":
    unittest.main()
