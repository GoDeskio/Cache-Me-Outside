import unittest
import namespaces as N


class T(unittest.TestCase):
    def test_rules(self):
        r = N.rules("acme")
        self.assertIn("~acme:*", r)
        self.assertIn("&acme:*", r)
        self.assertNotIn("~*", r)
        for c in ("-keys", "-scan", "-flushall", "-@scripting", "-config", "-acl"):
            self.assertIn(c, r)
        # deny rules must come after the allow so they win
        self.assertGreater(r.index("-keys"), r.index("+@all"))

    def test_readonly(self):
        r = N.rules("acme", readonly=True)
        self.assertIn("+@read", r)
        self.assertIn("-@write", r)
        self.assertNotIn("+@all", r)

    def test_create_and_bad_names(self):
        user, pw, cmd = N.create("acme")
        self.assertEqual(cmd[:6], ["ACL", "SETUSER", "ns-acme", "reset", "on", ">" + pw])
        self.assertEqual(N.create("acme", readonly=True)[0], "ns-acme-ro")
        for bad in ("A", "a*", "a:b", "x" * 40, "-x"):
            with self.assertRaises(ValueError):
                N.rules(bad)

    def test_remove(self):
        sent = []
        n = N.remove("acme", lambda *a: sent.append(a), lambda p: iter([["acme:1", "acme:2"], []]))
        self.assertEqual(n, 2)
        self.assertEqual(sent[0], ("ACL", "DELUSER", "ns-acme", "ns-acme-ro"))
        self.assertEqual(sent[1], ("UNLINK", "acme:1", "acme:2"))


if __name__ == "__main__":
    unittest.main()
