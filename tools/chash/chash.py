"""Weighted consistent-hash pool (plan #88). Independent rebuild; stdlib only.

Each server gets vnodes proportional to its weight on a 64-bit ring keyed by
blake2b. Adding or removing one server only moves the keys it owns.
"""
import bisect
import hashlib


def _h(data: str) -> int:
    return int.from_bytes(hashlib.blake2b(data.encode(), digest_size=8).digest(), "big")


class Ring:
    def __init__(self, servers, vnodes=160):
        """servers: dict name -> weight (float > 0)."""
        if not servers:
            raise ValueError("need at least one server")
        self.vnodes = vnodes
        self._ring = []
        for name, w in servers.items():
            if w <= 0:
                raise ValueError(f"bad weight for {name}")
            for i in range(max(1, int(round(vnodes * w)))):
                self._ring.append((_h(f"{name}#{i}"), name))
        self._ring.sort()
        self._keys = [k for k, _ in self._ring]

    def lookup(self, key: str) -> str:
        i = bisect.bisect(self._keys, _h(key)) % len(self._keys)
        return self._ring[i][1]

    def lookup_n(self, key: str, n: int):
        """First n distinct servers clockwise (for replicas/failover)."""
        out, i = [], bisect.bisect(self._keys, _h(key))
        names = {s for _, s in self._ring}
        n = min(n, len(names))
        while len(out) < n:
            s = self._ring[i % len(self._ring)][1]
            if s not in out:
                out.append(s)
            i += 1
        return out
