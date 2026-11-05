"""Write-path guards (plan #112-#116). Independent rebuilds from public Vitess docs.

- Rules: deny/allow command rules by command, key glob and user (#112)
- LagThrottler: slow writers when replica lag exceeds a threshold (#113)
- UserLimiter: per-user concurrency slots (#114)
- heartbeat_*: write a timestamp on the primary, read lag on replicas (#115)
- Queue: message queue on streams with ack and redelivery (#116)
"""
import fnmatch
import threading
import time


class Rules:
    def __init__(self, rules):
        """rules: [{"action": "deny"|"allow", "cmd": "FLUSH*", "key": "*", "user": "*"}], first match wins."""
        self.rules = rules

    def check(self, user, cmd, key=""):
        for r in self.rules:
            if (fnmatch.fnmatchcase(cmd.upper(), r.get("cmd", "*").upper()) and fnmatch.fnmatchcase(key, r.get("key", "*"))
                    and fnmatch.fnmatchcase(user, r.get("user", "*"))):
                return r["action"] == "allow", r
        return True, None


class LagThrottler:
    def __init__(self, threshold_s=1.0, max_delay_s=0.5):
        self.th, self.max = threshold_s, max_delay_s

    def delay(self, lags):
        worst = max(lags) if lags else 0
        if worst <= self.th:
            return 0.0
        return min(self.max, (worst - self.th) / self.th * self.max)


class UserLimiter:
    def __init__(self, per_user, overrides=None):
        self.n, self.over, self.used, self.lock = per_user, overrides or {}, {}, threading.Lock()

    def acquire(self, user):
        with self.lock:
            if self.used.get(user, 0) >= self.over.get(user, self.n):
                return False
            self.used[user] = self.used.get(user, 0) + 1; return True

    def release(self, user):
        with self.lock:
            self.used[user] = max(0, self.used.get(user, 0) - 1)


HB_KEY = "cmo:heartbeat"


def heartbeat_write(r, clock=time.time):
    r.set(HB_KEY, repr(clock()))


def heartbeat_lag(r, clock=time.time):
    v = r.get(HB_KEY)
    return None if v is None else max(0.0, clock() - float(v))


class Queue:
    """Stream-backed queue: ack removes, unacked messages redeliver after `visibility` seconds.
    `r` needs xadd/xreadgroup-like calls; this pure model is used by tests and as a reference."""

    def __init__(self, visibility=30, max_deliveries=5, clock=time.monotonic):
        self.vis, self.maxd, self.clock = visibility, max_deliveries, clock
        self.msgs, self.pending, self.dead, self.seq = [], {}, [], 0

    def push(self, body):
        self.seq += 1; self.msgs.append((self.seq, body, 0)); return self.seq

    def pull(self):
        now = self.clock()
        for mid, (body, n, due) in sorted(self.pending.items()):
            if due <= now:
                del self.pending[mid]
                if n >= self.maxd:
                    self.dead.append((mid, body)); continue
                self.msgs.insert(0, (mid, body, n))
        if not self.msgs:
            return None
        mid, body, n = self.msgs.pop(0)
        self.pending[mid] = (body, n + 1, now + self.vis)
        return mid, body

    def ack(self, mid):
        return self.pending.pop(mid, None) is not None
