#!/usr/bin/env python3
"""Plan prices. Flat per plan is the default. Per-GB-hour is optional.

Every rate in defaults.json is the string PLACEHOLDER. quote() refuses to
return a number until that rate is replaced.
"""
import json
import os
import sys

PLACEHOLDER = "PLACEHOLDER"
HERE = os.path.dirname(os.path.abspath(__file__))


def load(path=None):
    with open(path or os.path.join(HERE, "defaults.json")) as f:
        return json.load(f)


def quote(cat, plan_id, mode=None):
    """Return the rate string for a plan. Raises while it is still PLACEHOLDER."""
    mode = mode or cat.get("default_mode", "flat")
    plans = cat["plans"]
    if plan_id not in plans:
        raise KeyError("unknown plan %r" % plan_id)
    plan = plans[plan_id]
    if mode == "flat":
        rate = plan["price_month"]
    elif mode == "gb_hour":
        rate = plan["gb_hour"] if "gb_hour" in plan else cat["gb_hour"]
    else:
        raise ValueError("mode must be flat or gb_hour")
    if rate == PLACEHOLDER or not isinstance(rate, (int, float)):
        raise ValueError("%s %s rate is PLACEHOLDER" % (plan_id, mode))
    if rate < 0:
        raise ValueError("rate must be >= 0")
    return rate


def main(argv=None):
    p = __import__("argparse").ArgumentParser()
    p.add_argument("plan")
    p.add_argument("--mode", choices=("flat", "gb_hour"))
    a = p.parse_args(argv)
    cat = load()
    try:
        print(quote(cat, a.plan, a.mode))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
