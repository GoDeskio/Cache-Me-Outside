#!/usr/bin/env python3
"""Serverless plan: no node sizing, pooled cluster that auto-scales (plan item 39).

Tenants on the serverless plan share a pooled cluster behind the tenant proxy
(#19) with namespace isolation (#37) and are billed per request/GB (#9 meter).
This module decides when the pool grows or shrinks; the resharding planner
(#17/#18) moves slots. Scale out fast, scale in slowly, with a cooldown.
"""


class Autoscaler:
    def __init__(self, min_nodes=3, max_nodes=30, cpu_hi=0.70, cpu_lo=0.30,
                 mem_hi=0.75, mem_lo=0.40, cooldown_s=300, scale_in_after=3):
        self.min, self.max = min_nodes, max_nodes
        self.cpu_hi, self.cpu_lo, self.mem_hi, self.mem_lo = cpu_hi, cpu_lo, mem_hi, mem_lo
        self.cooldown, self.scale_in_after = cooldown_s, scale_in_after
        self.last_change, self.low_streak = -1e18, 0

    def decide(self, nodes, cpu, mem, now):
        """cpu, mem: pool averages 0..1. Returns target node count."""
        if now - self.last_change < self.cooldown:
            return nodes
        hi = max(cpu / self.cpu_hi, mem / self.mem_hi)
        if hi > 1:
            # size so the busier resource lands just under its high mark
            target = min(self.max, max(nodes + 1, -(-int(nodes * hi * 100) // 100)))
            self.low_streak = 0
        elif cpu < self.cpu_lo and mem < self.mem_lo:
            self.low_streak += 1
            if self.low_streak < self.scale_in_after:
                return nodes
            # never shrink so far that memory would cross its high mark
            floor = -(-int(nodes * mem * 1000) // int(self.mem_hi * 1000))
            target = max(self.min, floor, nodes - 1)
            self.low_streak = 0
        else:
            self.low_streak = 0
            return nodes
        if target != nodes:
            self.last_change = now
        return target
