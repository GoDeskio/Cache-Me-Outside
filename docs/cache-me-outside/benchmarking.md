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

The script authenticates to Cache-Me-Outside as the app user. The stock container gets the same CPU cap and memory limit, the same `maxmemory` and eviction policy, and the same AOF everysec and RDB save rules. Its password is a throwaway written into a config file mounted into the container. The app password is not placed on that container's command line. The ACL is not the same: the stock default user can run every command, including `CONFIG`, and the app user cannot. The results file records `save`, `appendonly`, and `appendfsync` for both, fetched with the admin user on Cache-Me-Outside and with the default user on stock. Each `valkey-benchmark` process runs in its own container on the Compose network, so it does not compete with the server's CPU cap.

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
- the app user can `SET` and `GET` a throwaway `cmo:smoke:<random>` key, which the default run deletes
- the app user is denied `FLUSHALL`, `FLUSHDB`, `DEBUG`, `CONFIG`, and `KEYS`
- the admin user can read config and `protected-mode` is `yes`
- the host port is not published on `0.0.0.0`
- `INFO server` contains `cmo_version` ending in `-cmo`, and `valkey_version` does not

The default run does not change the container memory limit, `maxmemory`, or the env file, and it does not restart the container. `--mutate` is the opt-in path that raises memory, rewrites `CMO_MAXMEMORY` back to the documented default, forces a snapshot, and checks the key after a restart.

```bash
./smoke.sh
./smoke.sh --mutate
```

Smoke, the failover test, and the cluster scale test use the `cmo-test` project unless `--i-know` is passed. CI calls `./smoke.sh --generate-env --mutate` on that project, which writes a gitignored `.env` with random passwords when one is not already present.
