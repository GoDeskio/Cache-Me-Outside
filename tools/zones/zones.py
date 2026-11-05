"""Zone-replicated cache client (plan #104-#107). Independent rebuild; stdlib only.

zones: dict zone -> handle (get/set/delete). Writes fan out to every zone and
complete per a latch policy; reads prefer the local zone and fall back to others.
"""
import threading


class LatchError(Exception):
    pass


class Throttled(Exception):
    pass


POLICIES = ("ONE", "QUORUM", "ALL_MINUS_1", "ALL")


def needed(policy, n):
    return {"ONE": 1, "QUORUM": n // 2 + 1, "ALL_MINUS_1": max(1, n - 1), "ALL": n}[policy]


class ZoneClient:
    def __init__(self, zones, local, policy="QUORUM", max_inflight=0):
        if local not in zones:
            raise ValueError("local zone missing")
        if policy not in POLICIES:
            raise ValueError(policy)
        self.zones, self.local, self.policy = dict(zones), local, policy
        self.sem = threading.BoundedSemaphore(max_inflight) if max_inflight else None
        self.stats = {"fallback_reads": 0, "throttled": 0}

    def _order(self):
        return [self.local] + [z for z in self.zones if z != self.local]

    def _gate(self):
        if self.sem and not self.sem.acquire(blocking=False):
            self.stats["throttled"] += 1
            raise Throttled("in-flight limit")  # 107

    def _ungate(self):
        if self.sem:
            self.sem.release()

    def _write(self, op, *a, policy=None, **kw):
        self._gate()
        try:
            ok, errs = 0, {}
            for z in self._order():
                try:
                    getattr(self.zones[z], op)(*a, **kw); ok += 1
                except Exception as e:  # noqa: BLE001
                    errs[z] = str(e)
            need = needed(policy or self.policy, len(self.zones))
            if ok < need:
                raise LatchError(f"{ok}/{len(self.zones)} zones, need {need}: {errs}")
            return {"ok": ok, "failed": sorted(errs)}
        finally:
            self._ungate()

    def set(self, k, v, ttl=None, policy=None):  # 104 + 105
        return self._write("set", k, v, ttl=ttl, policy=policy)

    def delete(self, k, policy=None):
        return self._write("delete", k, policy=policy)

    def get(self, k):  # 104
        self._gate()
        try:
            for i, z in enumerate(self._order()):
                try:
                    v = self.zones[z].get(k)
                except Exception:  # noqa: BLE001
                    continue
                if v is not None:
                    if i:
                        self.stats["fallback_reads"] += 1
                    return v
            return None
        finally:
            self._ungate()

    def get_bulk(self, keys):  # 106
        """Local zone first; only misses go to the next zone."""
        out, missing = {}, list(keys)
        for z in self._order():
            if not missing:
                break
            nxt = []
            for k in missing:
                try:
                    v = self.zones[z].get(k)
                except Exception:  # noqa: BLE001
                    v = None
                (nxt.append(k) if v is None else out.__setitem__(k, v))
            if z != self.local:
                self.stats["fallback_reads"] += len(missing) - len(nxt)
            missing = nxt
        return out
