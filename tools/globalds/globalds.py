#!/usr/bin/env python3
"""Global datastore: primary region + async read-replica regions (plan item 21).

- replica_config(): valkey.conf lines for a replica region following the
  primary over TLS.
- Router.pick(): send writes to the primary; send reads to the nearest healthy
  region whose replication lag is under the cap, else the primary.
- promote(): failover plan when the primary region is lost.
"""


def replica_config(primary_host, port=6380, user="repl", pw_file="/run/secrets/repl"):
    return ["replicaof %s %d" % (primary_host, port),
            "masteruser %s" % user,
            "include %s" % pw_file,  # file holds `masterauth <pw>`; never inline the secret
            "tls-replication yes",
            "replica-read-only yes",
            "replica-serve-stale-data yes"]


class Router:
    def __init__(self, primary, rtt, max_lag_s=2.0):
        """rtt: {client_region: {region: ms}}"""
        self.primary, self.rtt, self.max_lag = primary, rtt, max_lag_s
        self.state = {}  # region -> (healthy, lag_s)

    def report(self, region, healthy, lag_s=0.0):
        self.state[region] = (healthy, lag_s)

    def pick(self, client_region, write=False):
        if write:
            return self.primary
        ok = [r for r, (h, lag) in self.state.items()
              if h and (r == self.primary or lag <= self.max_lag)]
        if not ok:
            return self.primary
        dist = self.rtt.get(client_region, {})
        return min(ok, key=lambda r: (dist.get(r, 1e9), r != self.primary))


def promote(router):
    """Pick the healthy replica with least lag; return (new_primary, commands)."""
    cands = [(lag, r) for r, (h, lag) in router.state.items() if h and r != router.primary]
    if not cands:
        raise RuntimeError("no healthy replica region")
    new = min(cands)[1]
    cmds = [(new, ["REPLICAOF", "NO", "ONE"])]
    cmds += [(r, ["REPLICAOF", "<%s-host>" % new, "6380"]) for _, r in sorted(cands) if r != new]
    router.primary = new
    return new, cmds
