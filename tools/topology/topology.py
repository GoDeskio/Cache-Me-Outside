#!/usr/bin/env python3
"""Topology planning (plan items 19 placement, 75 SLA tiers, 76 rolling upgrades).

  python3 topology.py place hosts.json --shards 3 --replicas 1
  python3 topology.py sla placement.json
  python3 topology.py upgrade placement.json

hosts.json: [{"name": "h1", "zone": "a", "free_mb": 8192}, ...]
A placement is {"shards": [{"id": 0, "primary": "h1", "replicas": ["h2"]}], "hosts": [...]}.
SLA numbers are targets for the tier a topology qualifies for, not measurements.
"""
import argparse
import json
import sys

TIERS = [  # (name, availability target, rule)
    ("99.999", 0.99999, lambda t: t["min_copies"] >= 3 and t["zones_per_shard"] >= 3 and t["regions"] >= 2),
    ("99.99", 0.9999, lambda t: t["min_copies"] >= 2 and t["zones_per_shard"] >= 2),
    ("99.95", 0.9995, lambda t: t["min_copies"] >= 2),
    ("99.9", 0.999, lambda t: True),
]


def place(hosts, shards, replicas, mem_mb=0):
    """Put each shard's copies on distinct hosts, spreading across zones first.

    Picks least-loaded hosts; raises if a shard can't get distinct hosts.
    """
    if shards < 1 or replicas < 0:
        raise ValueError("Need shards >= 1 and replicas >= 0.")
    load = {h["name"]: 0 for h in hosts}
    free = {h["name"]: h.get("free_mb", 10 ** 9) for h in hosts}
    zone = {h["name"]: h.get("zone", "default") for h in hosts}
    out = []
    for s in range(shards):
        chosen, zones_used = [], set()
        for _ in range(replicas + 1):
            cands = [h for h in load if h not in chosen and free[h] >= mem_mb]
            if not cands:
                raise ValueError("Not enough hosts with %d MB free for shard %d." % (mem_mb, s))
            cands.sort(key=lambda h: (zone[h] in zones_used, load[h], h))
            h = cands[0]
            chosen.append(h)
            zones_used.add(zone[h])
            load[h] += 1
            free[h] -= mem_mb
        out.append({"id": s, "primary": chosen[0], "replicas": chosen[1:]})
    return {"shards": out, "hosts": hosts}


def summarize(p):
    zone = {h["name"]: h.get("zone", "default") for h in p["hosts"]}
    region = {h["name"]: h.get("region", "default") for h in p["hosts"]}
    copies = [1 + len(s["replicas"]) for s in p["shards"]]
    zps = [len({zone[h] for h in [s["primary"]] + s["replicas"]}) for s in p["shards"]]
    regs = [len({region[h] for h in [s["primary"]] + s["replicas"]}) for s in p["shards"]]
    return {"min_copies": min(copies), "zones_per_shard": min(zps), "regions": min(regs)}


def sla(p):
    t = summarize(p)
    for name, target, rule in TIERS:
        if rule(t):
            mins = round((1 - target) * 30 * 24 * 60, 1)
            return {"tier": name, "max_downtime_min_per_30d": mins, **t}


def upgrade_order(p):
    """Hosts in a safe rolling order: replica-only hosts first, then hosts holding
    primaries (fail those over before restarting). Never two copies of one shard at once."""
    prim = {}
    for s in p["shards"]:
        prim.setdefault(s["primary"], []).append(s["id"])
    steps = []
    for h in sorted(x["name"] for x in p["hosts"]):
        if h not in prim:
            steps.append({"host": h, "action": "restart"})
    for h in sorted(prim):
        steps.append({"host": h, "action": "failover-then-restart", "shards": prim[h]})
    for s in p["shards"]:
        if not s["replicas"] and s["primary"] in prim:
            for st in steps:
                if st["host"] == s["primary"]:
                    st["warning"] = "shard %d has no replica; expect downtime" % s["id"]
    return steps


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("place")
    pl.add_argument("hosts")
    pl.add_argument("--shards", type=int, default=1)
    pl.add_argument("--replicas", type=int, default=1)
    pl.add_argument("--mem-mb", type=int, default=0)
    for c in ("sla", "upgrade"):
        sub.add_parser(c).add_argument("placement")
    a = ap.parse_args(argv)
    if a.cmd == "place":
        out = place(json.load(open(a.hosts)), a.shards, a.replicas, a.mem_mb)
    else:
        p = json.load(open(a.placement))
        out = sla(p) if a.cmd == "sla" else upgrade_order(p)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
