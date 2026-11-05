#!/usr/bin/env python3
"""DB-grade durability: ack a write only after a log quorum (plan item 13).

The "strong" preset (#43) turns on appendfsync always on every node.
DurableClient sends the write, then WAITAOF 1 <quorum> <timeout>, which
returns once the write is fsynced locally and on <quorum> replicas (spread
across zones by the topology tool, #39). If the quorum is not reached in time
the caller gets NotDurable and must treat the write as unknown and retry
idempotently. It must never report success.
"""


class NotDurable(Exception):
    pass


def quorum(replicas):
    """Replica acks needed so a majority of (primary + replicas) hold the write."""
    return (replicas + 1) // 2


class DurableClient:
    def __init__(self, call, replicas, timeout_ms=1000):
        if replicas < 1:
            raise ValueError("multi-AZ durability needs at least one replica")
        self.call, self.need, self.timeout = call, quorum(replicas), timeout_ms

    def write(self, *argv):
        res = self.call(*argv)
        local, remote = self.call("WAITAOF", "1", str(self.need), str(self.timeout))
        if local < 1 or remote < self.need:
            raise NotDurable("fsynced local=%d replicas=%d need=%d" % (local, remote, self.need))
        return res
