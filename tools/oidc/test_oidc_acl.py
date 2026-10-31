import base64
import json
import unittest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
import oidc_acl as O

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def e(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jwk(k, kid="k1"):
    n = k.public_key().public_numbers()
    return {"kty": "RSA", "kid": kid, "n": e(n.n.to_bytes(256, "big")), "e": e(n.e.to_bytes(3, "big"))}


def tok(claims, key=KEY, alg="RS256"):
    h = e(json.dumps({"alg": alg, "kid": "k1"}).encode())
    p = e(json.dumps(claims).encode())
    sig = key.sign((h + "." + p).encode(), padding.PKCS1v15(), hashes.SHA256())
    return h + "." + p + "." + e(sig)


CFG = {"issuer": "https://iss", "audience": "cmo", "ttl": 600,
       "rules": [{"match": {"repository": "GoDeskio/app"}, "acl": "~app:* +@read"},
                 {"match": {"repository": "GoDeskio/admin"}, "acl": "~* +@all"}]}
GOOD = {"iss": "https://iss", "aud": "cmo", "exp": 2000, "sub": "s", "repository": "GoDeskio/app"}


class T(unittest.TestCase):
    def test_verify_ok_and_failures(self):
        J = [jwk(KEY)]
        self.assertEqual(O.verify(tok(GOOD), CFG, J, now=1000)["sub"], "s")
        for bad, msg in [({**GOOD, "iss": "x"}, "issuer"), ({**GOOD, "aud": "x"}, "audience"),
                         ({**GOOD, "exp": 10}, "expired")]:
            with self.assertRaisesRegex(O.AuthError, msg):
                O.verify(tok(bad), CFG, J, now=1000)
        with self.assertRaisesRegex(O.AuthError, "signature"):
            O.verify(tok(GOOD, OTHER), CFG, J, now=1000)
        with self.assertRaisesRegex(O.AuthError, "RS256"):
            O.verify(tok(GOOD, alg="none"), CFG, J, now=1000)
        with self.assertRaises(O.AuthError):
            O.verify("abc", CFG, J)

    def test_exchange_and_sweep(self):
        sent, now = [], [1000]
        iss = O.Issuer(CFG, lambda *a: sent.append(a), clock=lambda: now[0])
        out = iss.exchange(GOOD)
        self.assertTrue(out["username"].startswith("oidc-"))
        self.assertEqual(sent[0][:5], ("ACL", "SETUSER", out["username"], "reset", "on"))
        self.assertEqual(sent[0][5], ">" + out["password"])
        self.assertEqual(sent[0][6:], ("~app:*", "+@read"))
        self.assertEqual(iss.sweep(), [])
        now[0] += 601
        self.assertEqual(iss.sweep(), [out["username"]])
        self.assertEqual(sent[-1], ("ACL", "DELUSER", out["username"]))

    def test_rules_refuse(self):
        iss = O.Issuer(CFG, lambda *a: None)
        with self.assertRaisesRegex(O.AuthError, "No rule"):
            iss.exchange({**GOOD, "repository": "evil/x"})
        with self.assertRaisesRegex(O.AuthError, "admin"):
            iss.exchange({**GOOD, "repository": "GoDeskio/admin"})


if __name__ == "__main__":
    unittest.main()
