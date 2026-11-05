#!/usr/bin/env python3
"""Multi-tenant isolation for small plans: namespaces on a shared node (plan item 37).

Bigger plans get a container/VM per database (deploy/ + tenant proxy #19).
Small/free plans share a node; each tenant gets an ACL user locked to its own
key prefix and pub/sub channels, with dangerous and cross-keyspace commands
removed. This module builds those ACL rules; `apply(run)` sends them.
"""
import re
import secrets

NS = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
# Commands that see or change the whole keyspace / server, or run code.
DENY = ["-@admin", "-@dangerous", "-@scripting", "-keys", "-scan", "-flushdb", "-flushall",
        "-randomkey", "-swapdb", "-select", "-move", "-wait", "-waitaof", "-function",
        "-cluster", "-client", "-config", "-debug", "-monitor", "-module", "-acl", "-save",
        "-bgsave", "-bgrewriteaof", "-pubsub"]


def rules(ns, readonly=False):
    if not NS.match(ns):
        raise ValueError("namespace must be 2-31 chars of a-z, 0-9, -")
    base = ["reset", "on", "resetkeys", "resetchannels",
            "~%s:*" % ns, "&%s:*" % ns, "+@all" if not readonly else "+@read"]
    if readonly:
        base += ["+@connection", "-@write"]
    return base + DENY


def create(ns, readonly=False, password=None):
    pw = password or secrets.token_urlsafe(32)
    user = "ns-%s%s" % (ns, "-ro" if readonly else "")
    return user, pw, ["ACL", "SETUSER", user] + rules(ns, readonly)[:2] + [">" + pw] + rules(ns, readonly)[2:]


def remove(ns, run, scan):
    """Delete the tenant's users, then its keys (scan(pattern) yields key batches)."""
    run("ACL", "DELUSER", "ns-%s" % ns, "ns-%s-ro" % ns)
    n = 0
    for batch in scan("%s:*" % ns):
        if batch:
            run("UNLINK", *batch)
            n += len(batch)
    return n
