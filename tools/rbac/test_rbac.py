import unittest
import rbac as R


class T(unittest.TestCase):
    def test_inheritance(self):
        self.assertTrue(R.can("owner", "data.read"))
        self.assertTrue(R.can("admin", "db.create"))
        self.assertFalse(R.can("developer", "db.delete"))
        self.assertFalse(R.can("viewer", "data.read"))
        self.assertFalse(R.can("admin", "billing.manage"))
        with self.assertRaises(ValueError):
            R.can("god", "x")

    def test_assign_rules(self):
        self.assertTrue(R.can_assign("admin", "viewer", "developer", 2)[0])
        self.assertFalse(R.can_assign("admin", "viewer", "owner", 2)[0])
        self.assertFalse(R.can_assign("admin", "owner", None, 2)[0])
        self.assertFalse(R.can_assign("developer", "viewer", "developer", 2)[0])
        self.assertFalse(R.can_assign("owner", "owner", "admin", 1)[0])
        self.assertTrue(R.can_assign("owner", "owner", "admin", 2)[0])

    def test_sso(self):
        m = {"eng": "developer", "ops": "admin", "execs": "owner"}
        self.assertEqual(R.map_sso_groups(["eng", "ops"], m), "admin")
        self.assertEqual(R.map_sso_groups(["execs"], m), "admin")
        self.assertIsNone(R.map_sso_groups(["x"], m))
        self.assertEqual(R.map_sso_groups([], m, "viewer"), "viewer")


if __name__ == "__main__":
    unittest.main()
