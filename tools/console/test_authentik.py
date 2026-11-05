#!/usr/bin/env python3
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import authentik


class AuthentikTest(unittest.TestCase):
    def test_defaults_are_self_hosted_oidc(self):
        self.assertEqual(authentik.DEFAULTS["provider"], "authentik")
        self.assertEqual(authentik.DEFAULTS["protocol"], "oidc")
        self.assertEqual(authentik.DEFAULTS["hosted"], "self")
        self.assertEqual(authentik.DEFAULTS["roles"], ["viewer", "developer", "admin", "owner"])
        self.assertNotIn("owner", authentik.DEFAULT_GROUP_MAP.values())

    def test_group_mapping_matches_pr45_roles(self):
        self.assertEqual(authentik.role_for_groups(["cache-viewers"]), "viewer")
        self.assertEqual(
            authentik.role_for_groups(["cache-viewers", "cache-admins"]), "admin")
        self.assertIsNone(authentik.role_for_groups(["cache-owners"], {"cache-owners": "owner"}))
        self.assertEqual(
            authentik.role_for_groups(["cache-owners", "cache-developers"],
                                      {"cache-owners": "owner", "cache-developers": "developer"}),
            "developer")


if __name__ == "__main__":
    unittest.main()
