"""Spending caps for the tenant proxy (plan item 44).

The proxy asks a Budget whether a tenant may run commands. BudgetGuard
implements that by reading spend and cap from a CapSource, caching the answer
for `ttl` seconds so billing is not called per command.

CapSource is the interface the billing system fills in:
    status(tenant) -> {"spent_cents": int, "cap_cents": int | None}
cap_cents None (or 0) means no cap. Hostrack-Billing is the intended source;
see docs/cache-me-outside/spending-caps.md for the endpoint it must expose.
Until then FileCapSource reads the same shape from a local JSON file.
"""
import json
import os
import time
import urllib.request

from cmo_proxy import Budget


class CapSource:
    def status(self, tenant):
        raise NotImplementedError


class FileCapSource(CapSource):
    def __init__(self, path):
        self.path = path

    def status(self, tenant):
        with open(self.path) as f:
            return json.load(f).get(tenant, {})


class HttpCapSource(CapSource):
    """GET {base}/v1/spend/{tenant} with a bearer token from an env var."""

    def __init__(self, base, token_env="CMO_BILLING_TOKEN", timeout=3):
        if not base.startswith("https://"):
            raise ValueError("billing URL must be https")
        self.base = base.rstrip("/")
        self.token_env = token_env
        self.timeout = timeout

    def status(self, tenant):
        req = urllib.request.Request(f"{self.base}/v1/spend/{tenant}")
        token = os.environ.get(self.token_env)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)


class BudgetGuard(Budget):
    """fail_open=True keeps databases serving if billing is unreachable."""

    def __init__(self, source, ttl=30, fail_open=True, clock=time.monotonic):
        self.source = source
        self.ttl = ttl
        self.fail_open = fail_open
        self.clock = clock
        self.cache = {}

    def allow(self, tenant):
        hit = self.cache.get(tenant)
        now = self.clock()
        if hit and now - hit[0] < self.ttl:
            return hit[1]
        try:
            s = self.source.status(tenant)
            cap = s.get("cap_cents")
            ok = not cap or int(s.get("spent_cents", 0)) < int(cap)
        except Exception:
            ok = self.fail_open
        self.cache[tenant] = (now, ok)
        return ok
