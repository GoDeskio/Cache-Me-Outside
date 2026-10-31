import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import cmo_budget as b


class Src(b.CapSource):
    def __init__(self, data):
        self.data = data
        self.calls = 0

    def status(self, tenant):
        self.calls += 1
        if self.data is None:
            raise OSError("down")
        return self.data


class GuardTest(unittest.TestCase):
    def test_cap_and_cache(self):
        t = [0.0]
        s = Src({"spent_cents": 100, "cap_cents": 500})
        g = b.BudgetGuard(s, ttl=30, clock=lambda: t[0])
        self.assertTrue(g.allow("a"))
        s.data = {"spent_cents": 500, "cap_cents": 500}
        self.assertTrue(g.allow("a"))
        self.assertEqual(s.calls, 1)
        t[0] = 31
        self.assertFalse(g.allow("a"))

    def test_no_cap(self):
        self.assertTrue(b.BudgetGuard(Src({"spent_cents": 10**9, "cap_cents": None})).allow("a"))

    def test_fail_modes(self):
        self.assertTrue(b.BudgetGuard(Src(None)).allow("a"))
        self.assertFalse(b.BudgetGuard(Src(None), fail_open=False).allow("a"))

    def test_file_source(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"acme": {"spent_cents": 9, "cap_cents": 5}}, f)
        try:
            self.assertFalse(b.BudgetGuard(b.FileCapSource(f.name)).allow("acme"))
            self.assertTrue(b.BudgetGuard(b.FileCapSource(f.name)).allow("other"))
        finally:
            os.unlink(f.name)

    def test_http_requires_https(self):
        with self.assertRaises(ValueError):
            b.HttpCapSource("http://billing")


if __name__ == "__main__":
    unittest.main()
