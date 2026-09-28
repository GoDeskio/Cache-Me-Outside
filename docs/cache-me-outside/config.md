# Config

Runtime settings come from two places:

- `deploy/valkey.conf`, copied into the image at `/etc/cache-me-outside/valkey.conf`
- `deploy/.env`, passed into the container and used by the entrypoint

Passwords are not in the config file. The entrypoint writes `/tmp/cmo-users.acl` on each start.

## Environment

| Variable | Default | Role |
| --- | --- | --- |
| `CMO_ADMIN_USER` | `admin` | Full ACL user |
| `CMO_ADMIN_PASSWORD` | required | Admin password |
| `CMO_APP_USER` | `app` | Application user |
| `CMO_APP_PASSWORD` | required | App password, must differ from admin |
| `CMO_BIND_ADDRESS` | `127.0.0.1` | Host address published by Compose |
| `CMO_HOST_PORT` | `6379` | Host port |
| `CMO_PORT` | `6379` | Port inside the container |
| `CMO_MAXMEMORY` | `256mb` | `maxmemory` |
| `CMO_MAXMEMORY_POLICY` | `allkeys-lru` | Eviction policy |
| `CMO_CONTAINER_MEMORY` | `512m` | Docker memory limit. Keep it at least twice `CMO_MAXMEMORY` |
| `CMO_CPUS` | `1.0` | Compose CPU cap |
| `CMO_IO_THREADS` | `1` | Valkey `io-threads`. `1` is the main thread only |
| `CMO_REPLICAS` | `2` | Sentinel data replicas, not counting the primary |
| `CMO_SENTINELS` | `3` | Sentinel processes. Quorum is a majority unless `CMO_SENTINEL_QUORUM` is set |
| `CMO_SENTINEL_DOWN_AFTER_MS` | `5000` | How long Sentinel waits before calling a primary down |
| `CMO_SENTINEL_FAILOVER_TIMEOUT` | `60000` | Sentinel failover timeout |
| `CMO_SENTINEL_MEMORY` | `128m` | Memory limit for a Sentinel container |
| `CMO_SENTINEL_CPUS` | `1.0` | CPU cap for a Sentinel container. `0.25` or less can put Sentinel into TILT |
| `CMO_CLUSTER_PRIMARIES` | `3` | Initial cluster primaries. Minimum 3 |
| `CMO_CLUSTER_REPLICAS` | `1` | Replicas per primary |
| `CMO_CLUSTER_NODE_TIMEOUT` | `5000` | `cluster-node-timeout` |
| `CMO_ANNOUNCE_IP` | empty | Address other hosts use. Required for `./up.sh node`. Never `0.0.0.0` |
| `CMO_CONTAINER_BIND` | `0.0.0.0` | Address the process binds **inside** the container |
| `CMO_ENV_FILE` | `deploy/.env` | Env file used by the scripts and by Compose. Set this when the file is outside the repo |
| `CMO_NETWORK_ALIAS` | `cache-me-outside` | DNS name on `proxy-net`. `redis` and `valkey` are refused |
| `CMO_BENCH_OUT_DIR` | `deploy/results` | Directory for `bench.sh` reports |
| `CMO_BENCH_USER` | `app` | `admin` runs the benchmark as the admin user so it can `CONFIG` |
| `CMO_PROJECT` | `cache-me-outside` | Compose project name. Test scripts default to `cmo-test` |
| `CMO_NETWORK` | `cache-me-outside` | Docker network name for networks this tooling creates |
| `CMO_NAME_PREFIX` | `cache-me-outside` | Container and volume name prefix. The standalone container is this prefix |
| `CMO_PRODUCTION_PROJECT` | `cache-me-outside` | Name test scripts refuse unless `--i-know` is passed |
| `CMO_SUBNET` | unset | Optional IPv4 CIDR for the Compose network. See below |
| `CMO_REPL_USER` | unset | Optional replication user. Unset uses admin |
| `CMO_REPL_PASSWORD` | unset | Required when `CMO_REPL_USER` is set |
| `CMO_SENTINEL_USER` | unset | Optional Sentinel auth user. Unset uses admin |
| `CMO_SENTINEL_PASSWORD` | unset | Required when `CMO_SENTINEL_USER` is set |
| `CMO_CLUSTER_USER` | unset | Optional user for `valkey-cli --cluster`. Unset uses admin. This is not the cluster bus |
| `CMO_CLUSTER_PASSWORD` | unset | Required when `CMO_CLUSTER_USER` is set |

`CMO_CONTAINER_BIND` is not in the example env file. It has to be an address inside the container network namespace so published ports and `proxy-net` work. It is not the host bind. Host exposure is only `CMO_BIND_ADDRESS`.

`CMO_PROJECT`, `CMO_NETWORK`, and `CMO_NAME_PREFIX` default to `cache-me-outside` for a normal `./up.sh`. The standalone container name stays `cache-me-outside` and its volume stays `cache-me-outside-data`. Sentinel and cluster containers are prefixed: `cache-me-outside-primary`, `cache-me-outside-replica-N`, `cache-me-outside-sentinel-N`, and `cache-me-outside-cluster-N`. Setting the prefix to `cmo` would also rename the standalone container, so leave the default unless the whole project should move.

Test scripts (`smoke.sh`, `sentinel-failover.sh`, `cluster-scale-test.sh`) force `cmo-test` when those three are unset, and they refuse to run when any of them equals `CMO_PRODUCTION_PROJECT` or `cache-me-outside` unless you pass `--i-know`. `./down.sh` only deletes containers and volumes for the project it was given. A test run therefore does not remove a coexisting default-project container.

`CMO_SUBNET` is optional and has no default. On a busy Docker host the built-in address pools can be exhausted. Docker then hands the next network a `192.168.x.0/20` (or another range from those pools) that overlaps the LAN, and containers on that network lose the route to the LAN. Set `CMO_SUBNET` to a free IPv4 CIDR, prefix `/8` through `/28`, when that happens. The example `203.0.113.0/24` is TEST-NET-3 documentation space, not a range to put on a real LAN. The subnet is applied to the network this project creates. It is not applied to an external `proxy-net`.

Optional ACL users must differ from each other and from admin and app, including the passwords. Leave them unset to keep using admin. The Helm chart reads the same variables from optional Secret keys (`repl-user`, `repl-password`, `sentinel-user`, `sentinel-password`, `cluster-user`, `cluster-password`). A missing key leaves that variable unset.

`CMO_CONTAINER_MEMORY` should stay above `CMO_MAXMEMORY`. The process also needs memory for client buffers, the AOF, and fork-based snapshots.

Allowed eviction policies: `allkeys-lru`, `allkeys-lfu`, `allkeys-random`, `volatile-lru`, `volatile-lfu`, `volatile-random`, `volatile-ttl`, `noeviction`.

## Persistence

`deploy/valkey.conf` turns on both:

- AOF, `appendfsync everysec`, directory `/data/appendonlydir`
- RDB snapshots: 1 change after 3600s, 100 changes after 300s, 10000 changes after 60s, file `/data/dump.rdb`

On startup Valkey loads the AOF when it is enabled, because that is the more complete history. The volume keeps both.

## Process defaults that are not env vars

- `protected-mode yes`
- `daemonize no` (logs go to stdout)
- `stop-writes-on-bgsave-error yes`
- graceful stop: Compose sends SIGTERM and waits 20 seconds

Extra `valkey-server` arguments can be appended to `docker run` / the Compose `command:`. The entrypoint forwards `"$@"` after its own flags.
