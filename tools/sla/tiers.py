#!/usr/bin/env python3
"""Uptime tiers the service offers. Only these two."""

OFFERED = (
    {"name": "99.9", "percent": 99.9, "target": 0.999},
    {"name": "99.95", "percent": 99.95, "target": 0.9995},
)


def offered():
    return [dict(t) for t in OFFERED]


def names():
    return [t["name"] for t in OFFERED]


def downtime_minutes(name, days=30):
    for t in OFFERED:
        if t["name"] == name:
            return round((1.0 - t["target"]) * days * 24 * 60, 1)
    raise KeyError(name)
