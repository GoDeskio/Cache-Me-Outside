import unittest
import compliance as C

GOOD = """port 0
tls-port 6380
tls-replication yes
aclfile /etc/valkey/users.acl
appendonly yes
"""


class T(unittest.TestCase):
    def test_good(self):
        r = C.evaluate(GOOD)
        self.assertEqual(r["passed"], r["total"])
        self.assertEqual(len(r["config_sha256"]), 64)
        self.assertTrue(all(m["status"] == "needs owner" for m in r["manual"]))

    def test_bad(self):
        r = C.evaluate("port 6379\nprotected-mode no\nenable-debug-command yes\nuser default on nopass ~* +@all\n")
        failed = {x["id"] for x in r["automated"] if not x["pass"]}
        self.assertTrue({"ENC-TRANSIT", "AUTH-DEFAULT", "AUTH-PROTECTED", "BACKUP", "DANGEROUS-CMDS"} <= failed)

    def test_default_user_off(self):
        r = C.evaluate("user default off\n")
        self.assertTrue(next(x for x in r["automated"] if x["id"] == "AUTH-DEFAULT")["pass"])


if __name__ == "__main__":
    unittest.main()
