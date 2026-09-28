# Scaling

Three topologies ship together. Pick one with `deploy/up.sh`. You do not edit the compose files to change the replica count or the shard count; those are environment variables, and the add/remove scripts update the generated file.

| Topology | Command | Use it when |
| --- | --- | --- |
| Standalone | `./up.sh` | The working set fits on one machine and a restart is an acceptable outage |
| Sentinel | `./up.sh sentinel` | The working set still fits on one machine, but you want automatic failover and extra copies for reads |
| Cluster | `./up.sh cluster` | The working set or the write rate does not fit on one machine, so the keyspace has to be split into slots |

Scale **up** (more memory or CPU on the nodes you already have) before you scale **out**. A cluster of small nodes loses more to per-node overhead, failover, and client redirects than one larger node. Sentinel does not add memory capacity: every replica holds a full copy. Cluster does add capacity: each primary owns a slice of the 16384 slots.

## Scale up

These are plain settings in `deploy/.env`. Defaults are sized for a small home-lab VM, not a production box.

| Setting | Default | Guidance |
| --- | --- | --- |
| `CMO_MAXMEMORY` | `256mb` | The cache budget. Valkey `mb` is 1024×1024 |
| `CMO_MAXMEMORY_POLICY` | `allkeys-lru` | Right for a cache. Use `noeviction` only if a full cache must return errors instead of dropping keys |
| `CMO_CONTAINER_MEMORY` | `512m` | Docker's `m` is also 1024-based. Keep this at least **twice** `CMO_MAXMEMORY` so `BGREWRITEAOF` / `BGSAVE` can fork |
| `CMO_CPUS` | `1.0` | Container CPU cap. One core is enough until `valkey-benchmark` shows the process pegged |
| `CMO_IO_THREADS` | `1` | Main thread only. On this Valkey build, a value above 1 threads both reads and writes. Do not set it higher than `CMO_CPUS`. Valkey's own guidance is to leave a spare core and to bother only when a core is already busy |

Changing `CMO_CONTAINER_MEMORY`, `CMO_CPUS`, or `CMO_IO_THREADS` applies on the next `./up.sh` (the container is recreated). `maxmemory` can be raised on a live process:

```bash
# Give the cgroup room first if the container is already at the 2x ceiling.
# Then raise the cache. This refuses a decrease and refuses a value above
# half the live container limit.
./scale-memory.sh 384mb
./scale-memory.sh 384mb --all          # every data node in the running topology
./scale-memory.sh 384mb cache-me-outside-cluster-0  # one node
```

The helper uses the admin user (`CONFIG SET maxmemory`). It also writes `CMO_MAXMEMORY` in the env file (`CMO_ENV_FILE` or `deploy/.env`) so the next recreate does not snap back. A `docker restart` of an existing container keeps the environment from when that container was created; recreate with `./up.sh` to pick up the file.

Sentinel containers are not data nodes. The helper will not target them.

## Sentinel

```bash
# .env
CMO_REPLICAS=2          # full copies besides the primary
CMO_SENTINELS=3         # quorum is 2 unless CMO_SENTINEL_QUORUM is set
./up.sh sentinel
```

`deploy/render-topology.sh` writes `deploy/.generated/<project>/compose.yml`. With the default prefix the primary is `cache-me-outside-primary`, replicas are `cache-me-outside-replica-N`, and sentinels are `cache-me-outside-sentinel-N`. Each data node has its own volume. Each Sentinel also has a volume at `/data` and writes its config only when that file is missing, so a restart keeps the replicas it has already learned. Host ports start at `CMO_HOST_PORT` (6379) for the primary and step by one for each replica. Sentinel host ports start at `CMO_SENTINEL_PORT` (26379). All of them are published on `CMO_BIND_ADDRESS`, which defaults to `127.0.0.1`. `./up.sh` rejects `0.0.0.0`, `::`, and `*`. A different address per node is `CMO_BIND_ADDRESS_SENTINEL_1` (and the same for `2`, `3`, …) plus the bind stored for each data node when the topology is rendered.

Inside the Docker network the primary name is `cache-me-outside-primary`. Sentinels watch that name (`sentinel resolve-hostnames yes`) and authenticate as admin, or as `CMO_SENTINEL_USER` when that variable is set. The app user can ask Sentinel where the primary is and cannot run `SENTINEL FAILOVER`.

`CMO_SENTINEL_CPUS` defaults to `1.0`. A limit of `0.25` or less can pause the Sentinel process long enough that it enters TILT. TILT adds about 30 seconds before failover proceeds. The Helm chart uses the same one-CPU limit.

Application clients should be sentinel-aware and should use the app user against the data port. Point them at the three sentinel host ports.

Failover check (also what CI runs, with one replica and a short down-after):

```bash
CMO_REPLICAS=1 CMO_SENTINEL_DOWN_AFTER_MS=2000 ./smoke.sh --mutate sentinel
./sentinel-failover.sh --no-up
```

Those scripts use the `cmo-test` project unless `--i-know` is passed. The failover script waits until every Sentinel lists every replica, then disables the primary's restart policy and kills it. It waits until Sentinel publishes a different address and a write succeeds there.

To change the replica count, set `CMO_REPLICAS`, run `./down.sh`, then `./up.sh sentinel`. That deletes volumes. Adding a replica to a live Sentinel set is a new container with `CMO_ROLE=replica` and `CMO_PRIMARY_HOST` set to the current primary; the supported path for a count change on one machine is the env var plus a new render (`CMO_RESET_TOPOLOGY=1`).

## Cluster

```bash
CMO_CLUSTER_PRIMARIES=3
CMO_CLUSTER_REPLICAS=1    # per primary, so this is 6 nodes
./up.sh cluster
```

`./up.sh cluster` starts the nodes and runs `deploy/cluster-bootstrap.sh`, which is `valkey-cli --cluster create`. Every node starts as an empty cluster node (no `replicaof` in the config: that combination does not boot). The create command assigns replicas. The same ACL file is generated on every node. Replication uses admin, or `CMO_REPL_USER` when that variable is set. Cluster admin commands from these scripts use admin, or `CMO_CLUSTER_USER` when that variable is set. That user is not the cluster bus. Each node has its own volume, AOF `everysec`, and RDB. The app user still cannot `FLUSHALL`, `CONFIG`, `KEYS`, `CLUSTER MEET`, or `CLUSTER SETSLOT`.

On one machine the nodes announce their container hostname (`cluster-preferred-endpoint-type hostname`). Cluster redirects therefore resolve on the Docker network named by `CMO_NETWORK` (default `cache-me-outside`), which is where `valkey-cli -c` in these scripts runs. The host ports are still bound to `127.0.0.1` by default so a process on the host can open a single node, but a host client that follows redirects will be sent a container hostname. Use a client on the Docker network, or the multi-host announce settings below.

### Add a node

```bash
./cluster-add.sh primary
./cluster-add.sh replica cache-me-outside-cluster-0
```

`primary` starts a new container, `CLUSTER` add-node, then rebalance onto the empty primary. `replica` attaches to the named primary and does not take slots. Host ports are the next free port above the ones already in `deploy/.generated/<project>/state`, still on `CMO_BIND_ADDRESS`.

### Remove a node

```bash
./cluster-remove.sh cache-me-outside-cluster-3
```

A replica is deleted with `CLUSTER` del-node. A primary is refused if it is the last primary or if it still has replicas (remove those first). Otherwise every slot it owns is resharded to another primary, the script waits until it owns zero slots, deletes that container and its volume, and then rebalances the remaining primaries. Without that rebalance every slot stays on the one node that received the drain. Keys move with the slots.

The scale test CI runs, and the local check, is:

```bash
CMO_CLUSTER_PRIMARIES=3 CMO_CLUSTER_REPLICAS=0 ./cluster-scale-test.sh
```

That is the shared smoke test in cluster mode on the `cmo-test` project, then a fourth primary, a rebalance, a check that each primary owns slots and that every key is still readable, then a drain of that fourth node, another rebalance, and the same key and slot checks. It refuses to run against the default project unless `--i-know` is passed.

## Multi-host

One process per machine. Do not put a LAN address in git. On each machine, `deploy/.env` (mode `0600`, not committed) sets:

- `CMO_BIND_ADDRESS` to the address on that machine that peers will use. `127.0.0.1` if you are only testing on that host. Never `0.0.0.0`.
- `CMO_ANNOUNCE_IP` to that same reachable address. `./up.sh node` exits if this is missing or is `0.0.0.0` / `::` / `*`.
- `CMO_HOST_PORT` / `CMO_BUS_HOST_PORT` if 6379 / 16379 are taken. If those published ports differ from the ports inside the container, set `CMO_ANNOUNCE_PORT` and `CMO_ANNOUNCE_BUS_PORT` to the published ports. The simple case is to publish 6379 and 16379 as themselves.
- `CMO_ROLE=cluster` (the node-file default).

```bash
./up.sh node
```

From a machine that can open every node, with `valkey-cli` on the path or the image already built:

```bash
CMO_CLUSTER_NODES='<host-a>:6379,<host-b>:6379,<host-c>:6379' \
CMO_CLUSTER_REPLICAS=1 \
  ./cluster-bootstrap.sh
```

Those addresses are announce addresses, not container DNS names. The same admin password has to be in each machine's env file. `CMO_ENV_FILE` can point at a path outside the repo. Sentinel across machines is the same node file with `CMO_ROLE=primary` on one host, `CMO_ROLE=replica` and `CMO_PRIMARY_HOST=<announce address of the primary>` on the others, and `CMO_ROLE=sentinel` on three hosts. `CMO_ANNOUNCE_IP` is what replicas and sentinels publish so they are not advertising a Docker bridge address that the other machine cannot route to.

A VM installed from the `.deb` uses the same announce variables. The process binds `CMO_BIND_ADDRESS` (and loopback), not `0.0.0.0`. A Kubernetes pod uses in-cluster DNS unless `cluster.announce.mode` is `ip` and `hostPort` is enabled. Those three can be members of one cluster when each announce address is routable from the others. See [virtual machines](virtual-machines.md).

`CMO_ATTACH_PROXY_NET=1` on a single-host render also attaches the external network `proxy-net`. Create that network first. `./up.sh` does not attach it unless the variable is set, so a missing network does not block startup.

## Capacity

Rough planning numbers, per data node:

- Cache payload: `CMO_MAXMEMORY`
- Fork headroom: about another `CMO_MAXMEMORY` while a rewrite runs (copy-on-write, worse if the workload mutates during the rewrite)
- Client buffers and the replication backlog: start from Valkey's `repl-backlog-size` (1mb) and add what `INFO memory` shows for clients under load
- Fragmentation: often 10–20% on top of the used bytes

So a node with `CMO_MAXMEMORY=256mb` wants a container limit around `512m`, which is the default. If `deploy/bench.sh` shows evictions while CPU is idle, raise memory (scale up). If one node's CPU stays saturated with `CMO_IO_THREADS` already near `CMO_CPUS`, add a shard (scale out) rather than pretending another replica will absorb writes. Replicas help reads and failover. They do not split writes.

`./scale-memory.sh` enforces the half-limit rule so a live change cannot eat the fork headroom. It will not raise the cgroup. Raise `CMO_CONTAINER_MEMORY` and recreate first when you need a bigger cache.
