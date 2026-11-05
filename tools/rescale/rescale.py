#!/usr/bin/env python3
"""Online resharding planner (plan items 17 + 18).

Given the current slot ownership and a target node set (scale out / in),
compute the minimal set of slot moves so every node ends with an even share
(16384 slots, differing by at most 1). Moves are grouped into contiguous
ranges and emitted as Valkey 9 atomic slot migration commands
(`CLUSTER MIGRATESLOTS SLOTSRANGE a b NODE id`), run against the source node.
Vertical scaling (bigger node) = add new node, move its share, remove old.
"""
SLOTS = 16384


def targets(nodes):
    nodes = sorted(nodes)
    q, r = divmod(SLOTS, len(nodes))
    return {n: q + (1 if i < r else 0) for i, n in enumerate(nodes)}


def plan(owner, new_nodes):
    """owner: list of 16384 node ids. Returns list of (src, dst, start, end)."""
    if len(owner) != SLOTS:
        raise ValueError("need ownership for all 16384 slots")
    if not new_nodes:
        raise ValueError("need at least one node")
    want = targets(new_nodes)
    have = {}
    for n in owner:
        have[n] = have.get(n, 0) + 1
    # surplus: slots that must leave each node (all of a removed node's slots)
    surplus = {n: c - want.get(n, 0) for n, c in have.items() if c > want.get(n, 0)}
    need = {n: w - have.get(n, 0) for n, w in want.items() if w > have.get(n, 0)}
    new = list(owner)
    receivers = sorted(need)
    for slot in range(SLOTS):
        src = owner[slot]
        if surplus.get(src, 0) > 0 and receivers:
            dst = receivers[0]
            new[slot] = dst
            surplus[src] -= 1
            need[dst] -= 1
            if need[dst] == 0:
                receivers.pop(0)
    moves = []
    for slot in range(SLOTS):
        if new[slot] != owner[slot]:
            m = (owner[slot], new[slot])
            if moves and moves[-1][:2] == m and moves[-1][3] == slot - 1:
                moves[-1] = (m[0], m[1], moves[-1][2], slot)
            else:
                moves.append((m[0], m[1], slot, slot))
    return moves


def commands(moves):
    return [(src, ["CLUSTER", "MIGRATESLOTS", "SLOTSRANGE", str(a), str(b), "NODE", dst])
            for src, dst, a, b in moves]


def apply(moves, owner):
    out = list(owner)
    for src, dst, a, b in moves:
        for s in range(a, b + 1):
            assert out[s] == src
            out[s] = dst
    return out
