"""Cache Me Outside recipes (plan item 60): rate limit, lock, session, leaderboard.

Works with any client that can send a raw command. Pass a function
`call(*args)`, e.g. redis-py / valkey-py `r.execute_command`, or
`Resp(url).call` from tools/mcp/cmo_mcp.py. Written from the Valkey command
docs; no third-party recipe code.
"""
import secrets
import time

RELEASE = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "return redis.call('DEL', KEYS[1]) else return 0 end"
)
EXTEND = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "return redis.call('PEXPIRE', KEYS[1], ARGV[2]) else return 0 end"
)


class RateLimiter:
    """Fixed window: at most `limit` hits per `window_s` per id."""

    def __init__(self, call, prefix, limit, window_s, clock=time.time):
        self.call, self.prefix, self.limit, self.window, self.clock = call, prefix, limit, window_s, clock

    def hit(self, ident):
        now = self.clock()
        window = int(now // self.window)
        key = "%s:%s:%d" % (self.prefix, ident, window)
        n = int(self.call("INCR", key))
        if n == 1:
            self.call("PEXPIRE", key, int(self.window * 1000) + 1000)
        reset = (window + 1) * self.window - now
        return {"allowed": n <= self.limit, "remaining": max(0, self.limit - n), "reset_s": round(reset, 3)}


class Lock:
    """Single-node lock with a random owner token. Release/extend only by the owner."""

    def __init__(self, call, name, ttl_ms=10_000):
        self.call, self.key, self.ttl = call, "lock:" + name, ttl_ms
        self.token = None

    def acquire(self, wait_s=0.0, retry_s=0.05, sleep=time.sleep):
        token = secrets.token_hex(16)
        deadline = time.monotonic() + wait_s
        while True:
            if self.call("SET", self.key, token, "NX", "PX", self.ttl) == "OK":
                self.token = token
                return True
            if time.monotonic() >= deadline:
                return False
            sleep(retry_s)

    def extend(self, ttl_ms=None):
        return bool(self.token) and int(self.call("EVAL", EXTEND, 1, self.key, self.token, ttl_ms or self.ttl)) == 1

    def release(self):
        ok = bool(self.token) and int(self.call("EVAL", RELEASE, 1, self.key, self.token)) == 1
        self.token = None
        return ok

    def __enter__(self):
        if not self.acquire():
            raise TimeoutError("lock busy: " + self.key)
        return self

    def __exit__(self, *exc):
        self.release()


class Sessions:
    """Hash per session with a sliding idle timeout."""

    def __init__(self, call, prefix="sess", idle_s=1800):
        self.call, self.prefix, self.idle = call, prefix, idle_s

    def _k(self, sid):
        return "%s:%s" % (self.prefix, sid)

    def create(self, data):
        sid = secrets.token_urlsafe(24)
        flat = [x for kv in data.items() for x in kv]
        self.call("HSET", self._k(sid), *flat) if flat else self.call("HSET", self._k(sid), "_", "1")
        self.call("EXPIRE", self._k(sid), self.idle)
        return sid

    def get(self, sid):
        raw = self.call("HGETALL", self._k(sid)) or []
        if not raw:
            return None
        self.call("EXPIRE", self._k(sid), self.idle)
        d = dict(zip(raw[::2], raw[1::2]))
        d.pop("_", None)
        return d

    def destroy(self, sid):
        return int(self.call("DEL", self._k(sid))) == 1


class Leaderboard:
    def __init__(self, call, name):
        self.call, self.key = call, "lb:" + name

    def add(self, member, points):
        return float(self.call("ZINCRBY", self.key, points, member))

    def top(self, n=10):
        raw = self.call("ZREVRANGE", self.key, 0, n - 1, "WITHSCORES") or []
        return [(m, float(s)) for m, s in zip(raw[::2], raw[1::2])]

    def rank(self, member):
        r = self.call("ZREVRANK", self.key, member)
        return None if r is None else int(r) + 1
