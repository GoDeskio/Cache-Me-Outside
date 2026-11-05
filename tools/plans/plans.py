#!/usr/bin/env python3
"""Plan catalog and price quotes (plan items 41 fixed sizes, 42 free tier, 43 commitments).

  python3 plans.py list
  python3 plans.py quote m-4 --replicas 1 --years 1
  python3 plans.py fit 3000          # smallest size with >= 3000 MB
Prices live in plans.json so they can change without code changes.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path=None):
    with open(path or os.path.join(HERE, "plans.json")) as f:
        return json.load(f)


def find(cat, plan_id):
    if plan_id == "free":
        return cat["free"]
    for s in cat["sizes"]:
        if s["id"] == plan_id:
            return s
    raise KeyError("Unknown plan %r" % plan_id)


def quote(cat, plan_id, replicas=0, years=0):
    plan = find(cat, plan_id)
    if replicas < 0 or replicas > 5:
        raise ValueError("Replicas must be 0-5.")
    if plan_id == "free":
        if replicas or years:
            raise ValueError("The free tier has no replicas or commitments.")
        return {"plan": "free", "monthly": 0.0, "total": 0.0, "months": 1, "discount": 0.0}
    disc = {c["years"]: c["discount"] for c in cat["commitments"]}
    if years not in disc:
        raise ValueError("Commitment must be one of %s years." % sorted(disc))
    nodes = 1 + replicas * cat.get("replica_multiplier", 1.0)
    monthly = round(plan["price_month"] * nodes * (1 - disc[years]), 2)
    months = max(1, years * 12)
    return {"plan": plan_id, "replicas": replicas, "years": years, "discount": disc[years],
            "monthly": monthly, "months": months, "total": round(monthly * months, 2)}


def fit(cat, memory_mb):
    for s in sorted(cat["sizes"], key=lambda s: s["memory_mb"]):
        if s["memory_mb"] >= memory_mb:
            return s["id"]
    return None


def free_tier_allows(cat, used_commands, conns):
    f = cat["free"]
    return used_commands < f["monthly_commands"] and conns < f["max_conns"]


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    q = sub.add_parser("quote")
    q.add_argument("plan")
    q.add_argument("--replicas", type=int, default=0)
    q.add_argument("--years", type=int, default=0)
    fp = sub.add_parser("fit")
    fp.add_argument("memory_mb", type=int)
    a = p.parse_args(argv)
    cat = load()
    if a.cmd == "list":
        out = [cat["free"]] + cat["sizes"]
    elif a.cmd == "quote":
        out = quote(cat, a.plan, a.replicas, a.years)
    else:
        out = {"plan": fit(cat, a.memory_mb)}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
