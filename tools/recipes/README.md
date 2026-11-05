# Recipes (plan item 60)

`cmo_recipes.py` gives four helpers that take any `call(*args)` function:

```python
import valkey  # or redis
r = valkey.Valkey.from_url("rediss://app:PASS@host:6379")
from cmo_recipes import RateLimiter, Lock, Sessions, Leaderboard
rl = RateLimiter(r.execute_command, "rl:login", limit=5, window_s=60)
if not rl.hit(client_ip)["allowed"]: ...
with Lock(r.execute_command, "nightly-report", ttl_ms=30_000): ...
```

- **RateLimiter**: fixed window with INCR and PEXPIRE. Returns allowed, remaining and seconds to reset.
- **Lock**: SET NX PX with a random owner token; release and extend are Lua compare-and-act so only the owner can do them. Single-node lock: not safe across a failover. Use it for de-duplicating work, not for correctness-critical mutual exclusion.
- **Sessions**: one hash per session with a sliding idle timeout.
- **Leaderboard**: sorted set with ZINCRBY, top N and 1-based rank.

Tests: `python3 tools/recipes/test_cmo_recipes.py`. They use an in-memory fake, so the two Lua scripts are checked by meaning, not run on Valkey.
