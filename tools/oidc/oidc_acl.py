#!/usr/bin/env python3
"""OIDC token -> short-lived Valkey ACL user (plan item 31). No static passwords.

A workload sends its OIDC ID token (GitHub Actions, Kubernetes, Google, Entra...)
to POST /token. If the token's issuer, audience, signature (RS256 via the
issuer's JWKS) and expiry check out and its claims match a rule, we create
an ACL user `oidc-<hash>` with a random password and that rule's ACL, valid
for `ttl` seconds, and return the username and password. A sweeper deletes
expired users. Rules come from JSON:

  {"issuer": "https://token.actions.githubusercontent.com", "audience": "cmo",
   "ttl": 900,
   "rules": [{"match": {"repository": "GoDeskio/app"}, "acl": "~app:* +@read +@write -@dangerous"}]}

Needs the `cryptography` package for RS256.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class AuthError(Exception):
    pass


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwk_to_key(jwk):
    n = int.from_bytes(b64d(jwk["n"]), "big")
    e = int.from_bytes(b64d(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def fetch_jwks(issuer):
    with urllib.request.urlopen(issuer.rstrip("/") + "/.well-known/openid-configuration", timeout=5) as r:
        uri = json.load(r)["jwks_uri"]
    with urllib.request.urlopen(uri, timeout=5) as r:
        return json.load(r)["keys"]


def verify(token, cfg, jwks, now=None, leeway=60):
    now = now or time.time()
    try:
        h64, p64, s64 = token.split(".")
        header, claims = json.loads(b64d(h64)), json.loads(b64d(p64))
    except (ValueError, json.JSONDecodeError):
        raise AuthError("Malformed token")
    if header.get("alg") != "RS256":
        raise AuthError("Only RS256 tokens are accepted")
    keys = [k for k in jwks if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"]
    if not keys:
        raise AuthError("Unknown signing key")
    try:
        jwk_to_key(keys[0]).verify(b64d(s64), (h64 + "." + p64).encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise AuthError("Bad signature")
    if claims.get("iss") != cfg["issuer"]:
        raise AuthError("Wrong issuer")
    aud = claims.get("aud")
    if cfg["audience"] not in (aud if isinstance(aud, list) else [aud]):
        raise AuthError("Wrong audience")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] + leeway < now:
        raise AuthError("Token expired")
    if claims.get("nbf", 0) - leeway > now:
        raise AuthError("Token not yet valid")
    return claims


def pick_rule(cfg, claims):
    for r in cfg["rules"]:
        if all(claims.get(k) == v for k, v in r["match"].items()):
            return r
    raise AuthError("No rule allows this identity")


class Issuer:
    """Creates and sweeps temporary ACL users. `run(*args)` sends one command to Valkey."""

    def __init__(self, cfg, run, clock=time.time):
        self.cfg, self.run, self.clock = cfg, run, clock
        self.live = {}

    def exchange(self, claims):
        rule = pick_rule(self.cfg, claims)
        acl = rule["acl"].split()
        if any(a.lower() in ("allcommands", "+@all", "nopass", "allkeys", "~*") for a in acl) and not rule.get("admin_ok"):
            raise AuthError("Rule grants admin-level access; set admin_ok to allow")
        ttl = min(int(rule.get("ttl", self.cfg.get("ttl", 900))), 3600)
        ident = hashlib.sha256((claims["iss"] + "|" + str(claims.get("sub"))).encode()).hexdigest()[:16]
        user = "oidc-%s-%s" % (ident, secrets.token_hex(4))
        pw = secrets.token_urlsafe(32)
        self.run("ACL", "SETUSER", user, "reset", "on", ">" + pw, *acl)
        self.live[user] = self.clock() + ttl
        return {"username": user, "password": pw, "expires_in": ttl}

    def sweep(self):
        now, gone = self.clock(), []
        for u, exp in list(self.live.items()):
            if exp <= now:
                self.run("ACL", "DELUSER", u)
                del self.live[u]
                gone.append(u)
        return gone
