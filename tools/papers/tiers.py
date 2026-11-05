"""Paper-derived data models, part 1 (plan #118, #121-#123). Written from the TAO and Bigtable papers only.

- TieredCache: follower tier -> leader tier -> DB; writes go through the leader, which
  invalidates followers (#118).
- VersionedRow: column families with timestamped cells and GC by max versions / max age (#121).
- plan_splits(): split ranges above max bytes, merge neighbours below min bytes (#122).
- locality_tier(): put column families in hot or cold groups by access rate (#123).
"""
import bisect


class TieredCache:
    def __init__(self, db, followers=2):
        self.db, self.leader, self.followers = db, {}, [dict() for _ in range(followers)]

    def read(self, k, f=0):
        tier = self.followers[f]
        if k in tier: return tier[k], "follower"
        if k not in self.leader:
            self.leader[k] = self.db.get(k); src = "db"
        else:
            src = "leader"
        tier[k] = self.leader[k]
        return tier[k], src

    def write(self, k, v):
        self.db[k] = v; self.leader[k] = v
        for t in self.followers: t.pop(k, None)


class VersionedRow:
    def __init__(self, families):
        """families: {name: {"max_versions": int, "max_age": seconds or None}}"""
        self.fam, self.cells = families, {}

    def put(self, fam, col, ts, val):
        if fam not in self.fam: raise KeyError(fam)
        lst = self.cells.setdefault((fam, col), [])
        bisect.insort(lst, (-ts, val))

    def get(self, fam, col, at=None, versions=1):
        lst = self.cells.get((fam, col), [])
        return [(-t, v) for t, v in lst if at is None or -t <= at][:versions]

    def gc(self, now):
        for (fam, col), lst in self.cells.items():
            spec = self.fam[fam]
            if spec.get("max_age") is not None:
                lst[:] = [c for c in lst if now - (-c[0]) <= spec["max_age"]]
            del lst[spec.get("max_versions", 1 << 30):]


def plan_splits(ranges, max_bytes, min_bytes):
    """ranges: sorted [(start_key, bytes)]. Returns actions."""
    acts = [("split", s) for s, b in ranges if b > max_bytes]
    i = 0
    while i < len(ranges) - 1:
        (s1, b1), (s2, b2) = ranges[i], ranges[i + 1]
        if b1 < min_bytes and b2 < min_bytes and b1 + b2 <= max_bytes:
            acts.append(("merge", s1, s2)); i += 2
        else:
            i += 1
    return acts


def locality_tier(rates, hot_share=0.8):
    """rates: {family: reads/s}. Families making up the top `hot_share` of reads are hot."""
    tot, acc, out = sum(rates.values()) or 1, 0, {}
    for f in sorted(rates, key=rates.get, reverse=True):
        out[f] = "hot" if acc < hot_share * tot else "cold"; acc += rates[f]
    return out
