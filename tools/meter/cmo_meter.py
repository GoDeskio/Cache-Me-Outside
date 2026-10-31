#!/usr/bin/env python3
"""Hourly usage metering for Cache Me Outside -> Hostrack-Billing.

Two pricing modes, chosen globally ("mode") or per tenant:
  plan     flat monthly price per plan (default), charged per hour as
           monthly_cents / 730 so a database billed part of a month pays for
           the hours it existed
  gb_hour  used memory (INFO memory used_memory) in GB x gb_hour_cents

Run once an hour (cron/systemd timer). Each run charges the hours since the
last charged hour (at most 24, to catch up after downtime without runaway
bills), keeps fractional cents in a state file so nothing is lost to
rounding, and posts whole cents to Hostrack-Billing admin API
hrplatform/spend_record. Re-running within the same hour charges nothing.

  CMO_BILLING_API_KEY=... python3 cmo_meter.py pricing.json state.json
  python3 cmo_meter.py pricing.json state.json --dry-run

Rates in pricing.example.json are placeholders (null). The meter refuses to
run while a rate it needs is null. Per-tenant DB passwords come from env
CMO_METER_PASSWORD_<TENANT> (upper-case, '-' -> '_'), user from
CMO_METER_USER (default "default").
"""
import base64
import json
import os
import socket
import sys
import time
import urllib.request

HOURS_PER_MONTH = 730
MAX_CATCHUP_HOURS = 24
GB = 1024 ** 3


def resp_cmd(sock, f, *args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        a = a.encode() if isinstance(a, str) else a
        out += b"$%d\r\n%s\r\n" % (len(a), a)
    sock.sendall(out)
    line = f.readline()
    if line[:1] == b"-":
        raise RuntimeError(line[1:].strip().decode())
    if line[:1] == b"$":
        n = int(line[1:])
        return f.read(n + 2)[:-2].decode()
    return line[1:].strip().decode()


def used_memory(host, port, user, password, timeout=5):
    with socket.create_connection((host, port), timeout=timeout) as s, s.makefile("rb") as f:
        if password:
            resp_cmd(s, f, "AUTH", user, password)
        info = resp_cmd(s, f, "INFO", "memory")
    for line in info.splitlines():
        if line.startswith("used_memory:"):
            return int(line.split(":", 1)[1])
    raise RuntimeError("used_memory missing from INFO")


def tenant_mode(cfg, t):
    mode = t.get("mode", cfg.get("mode", "plan"))
    if mode not in ("plan", "gb_hour"):
        raise ValueError(f"unknown mode {mode!r}")
    return mode


def validate(cfg):
    """Raise if any rate the configured tenants need is still a placeholder."""
    for name, t in cfg["tenants"].items():
        mode = tenant_mode(cfg, t)
        if mode == "plan":
            plan = cfg.get("plans", {}).get(t.get("plan"))
            if plan is None:
                raise ValueError(f"{name}: unknown plan {t.get('plan')!r}")
            if not isinstance(plan.get("monthly_cents"), int) or plan["monthly_cents"] < 0:
                raise ValueError(f"{name}: plan {t['plan']} has a placeholder price; set monthly_cents")
        else:
            rate = t.get("gb_hour_cents", cfg.get("gb_hour_cents"))
            if not isinstance(rate, (int, float)) or rate < 0:
                raise ValueError(f"{name}: gb_hour_cents is a placeholder; set it")
            if not t.get("host") or not t.get("port"):
                raise ValueError(f"{name}: gb_hour needs host and port")


def hourly_cents(cfg, name, t, memory_fn):
    """Exact (fractional) cents for one hour of this tenant."""
    if tenant_mode(cfg, t) == "plan":
        return cfg["plans"][t["plan"]]["monthly_cents"] / HOURS_PER_MONTH
    rate = t.get("gb_hour_cents", cfg.get("gb_hour_cents"))
    return memory_fn(name, t) / GB * rate


def run(cfg, state, now, memory_fn, post_fn, dry_run=False):
    validate(cfg)
    hour = int(now // 3600)
    report = {}
    for name, t in cfg["tenants"].items():
        s = state.setdefault(name, {"last_hour": hour - 1, "carry": 0.0})
        hours = min(hour - s["last_hour"], MAX_CATCHUP_HOURS)
        if hours <= 0:
            report[name] = 0
            continue
        exact = hourly_cents(cfg, name, t, memory_fn) * hours + s["carry"]
        cents = int(exact)
        if not dry_run:
            if cents:
                post_fn(name, cents)
            s["carry"] = exact - cents
            s["last_hour"] = hour
        report[name] = cents
    return report


def make_post(base, key):
    if not base.startswith("https://"):
        raise ValueError("billing_url must be https")
    auth = base64.b64encode(f"admin:{key}".encode()).decode()

    def post(tenant, cents):
        body = json.dumps({"tenant": tenant, "cents": cents}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/api/admin/hrplatform/spend_record", body,
                                     {"Content-Type": "application/json", "Authorization": "Basic " + auth})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.load(r)
        if res.get("error"):
            raise RuntimeError(f"{tenant}: {res['error']}")
    return post


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    with open(argv[1]) as f:
        cfg = json.load(f)
    try:
        with open(argv[2]) as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    dry = "--dry-run" in argv
    user = os.environ.get("CMO_METER_USER", "default")

    def mem(name, t):
        pw = os.environ.get("CMO_METER_PASSWORD_" + name.upper().replace("-", "_"), "")
        return used_memory(t["host"], int(t["port"]), user, pw)

    post = None if dry else make_post(cfg["billing_url"], os.environ["CMO_BILLING_API_KEY"])
    report = run(cfg, state, time.time(), mem, post, dry)
    if not dry:
        tmp = argv[2] + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, argv[2])
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
