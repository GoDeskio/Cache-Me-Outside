# Benchmarking

`deploy/bench.sh` runs `valkey-benchmark` against the Compose container and against a stock `valkey/valkey` container, then writes `bench-<utc>.txt`. The default directory is `deploy/results`, which is gitignored. Set `CMO_BENCH_OUT_DIR` to put the file somewhere else (an absolute path, or a path relative to `deploy/`).

The cache must already be up (`./up.sh` or `./smoke.sh`). The script reads `CMO_ENV_FILE` or `deploy/.env` and does not print passwords.

```bash
cd deploy
./bench.sh
```

Defaults are 100000 requests, 20 clients, 64-byte values, `SET` and `GET`. Override them without editing the script:

```bash
CMO_BENCH_REQUESTS=20000 CMO_BENCH_CLIENTS=10 ./bench.sh
```

The script authenticates to Cache-Me-Outside as the app user. The stock container uses `--requirepass` with that same password on the default user, the same `maxmemory` and eviction policy, and the same AOF everysec and RDB save rules. The ACL is not the same: the stock default user can run every command, including `CONFIG`, and the app user cannot. The results file records `save`, `appendonly`, and `appendfsync` for both, fetched with the admin user on Cache-Me-Outside and with the default user on stock. Each `valkey-benchmark` process runs inside the container it measures, against `127.0.0.1`, so the Docker network is not part of the timing.

`valkey-benchmark` tries `CONFIG GET` before the test. Against the app user that call is denied. The script drops the single warning line `Could not fetch server CONFIG` and keeps the admin-fetched values in the header. Set `CMO_BENCH_USER=admin` when you want the benchmark client itself to be a user that can `CONFIG`.

## Upstream image tag

`INFO server` `valkey_version` on this branch is `255.255.255` (Valkey's unstable version). Docker Hub does not publish `valkey/valkey:255.255.255`. The script tries, in order:

1. `valkey/valkey:<valkey_version>`
2. `valkey/valkey:unstable` when the version is `255.*`
3. `valkey/valkey:8`

The file records which image was actually pulled. The stock container publishes `127.0.0.1:16379` only, then it is removed on exit.

## memtier

If `memtier_benchmark` is on `PATH`, the script also runs a short mixed workload against the host publish address. If it is missing, that section is marked skipped and the script still succeeds.

## Smoke test

`deploy/smoke.sh` is the functional check, not a benchmark. It confirms:

- unauthenticated `PING` is `NOAUTH`
- the app user can `SET` and `GET`
- the app user is denied `FLUSHALL`, `FLUSHDB`, `DEBUG`, `CONFIG`, and `KEYS`
- the admin user can read config and `protected-mode` is `yes`
- the host port is not published on `0.0.0.0`
- `INFO server` contains `cmo_version` ending in `-cmo`, and `valkey_version` does not
- an RDB file and the AOF directory exist, and the key is still there after `docker compose restart`

```bash
./smoke.sh
```

CI calls `./smoke.sh --generate-env`, which writes a gitignored `.env` with random passwords when one is not already present.
