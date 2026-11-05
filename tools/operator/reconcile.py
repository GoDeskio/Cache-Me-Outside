#!/usr/bin/env python3
"""Kubernetes operator core: reconcile a CacheCluster spec (plan item 74).

The Helm chart stays the simple install. The operator watches CacheCluster
custom resources and calls reconcile(spec, observed) on each change. It
returns an ordered action list, applied one step per loop (a level-triggered
controller). Kubernetes client wiring is separate so this logic is testable.

spec:     {"shards": int, "replicas": int, "version": str}
observed: {"pods": [{"name", "shard", "role": "primary"|"replica", "version", "ready"}]}
"""


def reconcile(spec, observed):
    pods = observed.get("pods", [])
    if any(not p["ready"] for p in pods):
        return [("wait", "pods not ready")]
    by = {}
    for p in pods:
        by.setdefault(p["shard"], []).append(p)
    acts = []
    # 1. shards with no primary: promote a replica (failover first)
    for s, ps in sorted(by.items()):
        if not any(p["role"] == "primary" for p in ps) and ps:
            return [("promote", ps[0]["name"])]
    # 2. scale out shards, then move slots
    for s in range(len(by), spec["shards"]):
        acts.append(("create_shard", s))
    if acts:
        return acts + [("rebalance", spec["shards"])]
    # 3. scale in: move slots off, then delete
    extra = sorted(s for s in by if s >= spec["shards"])
    if extra:
        return [("rebalance", spec["shards"])] + [("delete_shard", s) for s in extra]
    # 4. replicas per shard
    for s, ps in sorted(by.items()):
        reps = [p for p in ps if p["role"] == "replica"]
        if len(reps) < spec["replicas"]:
            acts.append(("add_replica", s))
        for p in sorted(reps, key=lambda p: p["name"])[spec["replicas"]:]:
            acts.append(("delete_pod", p["name"]))
    if acts:
        return acts
    # 5. rolling upgrade: one pod at a time, replicas first, primary via failover
    for s, ps in sorted(by.items()):
        old = [p for p in ps if p["version"] != spec["version"]]
        for p in sorted(old, key=lambda p: p["role"] == "primary"):
            if p["role"] == "primary":
                return [("failover", p["name"])]
            return [("upgrade", p["name"])]
    return []
