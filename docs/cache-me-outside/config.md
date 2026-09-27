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
| `CMO_SENTINEL_CPUS` | `0.25` | CPU cap for a Sentinel container |
| `CMO_CLUSTER_PRIMARIES` | `3` | Initial cluster primaries. Minimum 3 |
| `CMO_CLUSTER_REPLICAS` | `1` | Replicas per primary |
| `CMO_CLUSTER_NODE_TIMEOUT` | `5000` | `cluster-node-timeout` |
| `CMO_ANNOUNCE_IP` | empty | Address other hosts use. Required for `./up.sh node`. Never `0.0.0.0` |
| `CMO_CONTAINER_BIND` | `0.0.0.0` | Address the process binds **inside** the container |

`CMO_CONTAINER_BIND` is not in the example env file. It has to be an address inside the container network namespace so published ports and `proxy-net` work. It is not the host bind. Host exposure is only `CMO_BIND_ADDRESS`.

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
