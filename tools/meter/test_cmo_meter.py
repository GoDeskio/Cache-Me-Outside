import json
import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import cmo_meter as m

H = 3600


def cfg(**kw):
    c = {"mode": "plan", "plans": {"starter": {"monthly_cents": 730}}, "gb_hour_cents": 2,
         "tenants": {"a": {"plan": "starter"}}}
    c.update(kw)
    return c


class MeterTest(unittest.TestCase):
    def test_example_is_placeholder_and_refused(self):
        with open(os.path.join(os.path.dirname(__file__), "pricing.example.json")) as f:
            ex = json.load(f)
        with self.assertRaisesRegex(ValueError, "placeholder"):
            m.validate(ex)

    def test_plan_hourly_and_idempotent(self):
        posts = []
        st = {}
        c = cfg()
        m.run(c, st, 100 * H, None, lambda t, n: posts.append((t, n)))
        self.assertEqual(posts, [("a", 1)])  # 730/730 per hour
        m.run(c, st, 100 * H + 59, None, lambda t, n: posts.append((t, n)))
        self.assertEqual(len(posts), 1)

    def test_carry_keeps_fractions(self):
        posts = []
        st = {}
        c = cfg(plans={"starter": {"monthly_cents": 365}})  # 0.5 cent/hour
        for h in range(1, 5):
            m.run(c, st, (100 + h) * H, None, lambda t, n: posts.append(n))
        self.assertEqual(sum(posts), 2)

    def test_catchup_capped(self):
        posts = []
        st = {"a": {"last_hour": 0, "carry": 0.0}}
        m.run(cfg(), st, 1000 * H, None, lambda t, n: posts.append(n))
        self.assertEqual(posts, [24])

    def test_gb_hour(self):
        posts = []
        c = cfg(tenants={"b": {"mode": "gb_hour", "host": "h", "port": 1}}, gb_hour_cents=3)
        m.run(c, {}, 5 * H, lambda n, t: 2 * m.GB, lambda t, n: posts.append(n))
        self.assertEqual(posts, [6])

    def test_dry_run_does_not_advance(self):
        st = {}
        r = m.run(cfg(), st, 7 * H, None, None, dry_run=True)
        self.assertEqual(r, {"a": 1})
        self.assertNotIn("carry", {k for v in st.values() for k in v if v["last_hour"] == 7})

    def test_https_only(self):
        with self.assertRaises(ValueError):
            m.make_post("http://billing", "k")


class RespTest(unittest.TestCase):
    def test_info_memory(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        seen = []

        def serve():
            c, _ = srv.accept()
            f = c.makefile("rb")
            for reply in (b"+OK\r\n", None):
                n = int(f.readline()[1:])
                args = []
                for _ in range(n):
                    size = int(f.readline()[1:])
                    args.append(f.read(size + 2)[:-2])
                seen.append(args)
                if reply is None:
                    body = b"# Memory\r\nused_memory:1048576\r\n"
                    reply = b"$%d\r\n%s\r\n" % (len(body), body)
                c.sendall(reply)
            c.close()

        th = threading.Thread(target=serve)
        th.start()
        self.assertEqual(m.used_memory("127.0.0.1", port, "meter", "pw"), 1048576)
        th.join()
        srv.close()
        self.assertEqual(seen[0], [b"AUTH", b"meter", b"pw"])


if __name__ == "__main__":
    unittest.main()
