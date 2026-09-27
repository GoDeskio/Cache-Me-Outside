# Virtual machines

The same server that runs in Docker can be installed on a Debian or Ubuntu VM with a `.deb`, a systemd unit, and the same ACL and persistence defaults. Containers, pods, and VMs can share one replication group or cluster when every node has an address the others can route to.

No passwords and no real network addresses are in this tree. Examples use `203.0.113.0/24`, which is TEST-NET-3 documentation space.

## Package

On a build machine, from the repo root:

```bash
make -j"$(nproc)"
./packaging/build-deb.sh
```

That writes `dist/cache-me-outside_<version>_<arch>.deb`. Build it on Debian 12 or Ubuntu with a glibc no newer than the machines that will install it. A binary built on a newer host will not start on Bookworm. CI compiles inside a Debian 12 container for that reason. The package does not start the server. `postinst` creates a `valkey` system user and, if `/etc/cache-me-outside/environment` is missing, copies the example file. The example passwords are placeholders. The server refuses them.

```bash
sudo dpkg -i dist/cache-me-outside_*.deb
sudo editor /etc/cache-me-outside/environment
sudo systemctl enable --now cache-me-outside.service
```

The unit is `cache-me-outside.service`. It runs as `valkey`, with `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, a private `/tmp`, and no capabilities. `ExecStop` is `SHUTDOWN SAVE` on data nodes, so a stop flushes the dataset before the process exits. Sentinel uses `cache-me-outside-sentinel.service` and `SHUTDOWN NOSAVE`.

Data is `/var/lib/cache-me-outside` (AOF and RDB, the same rules as `deploy/valkey.conf`). The ACL file is written under `/run` on each start and is not on the data directory.

`CMO_BIND_ADDRESS` defaults to `127.0.0.1`. The process also listens on `127.0.0.1` when the public address is different, so shutdown and local checks keep working. `0.0.0.0`, `::`, and `*` are refused. Set `CMO_BIND_ADDRESS` to one address other machines should use.

## Roles

Standalone is the default.

Replica:

```
CMO_ROLE=replica
CMO_PRIMARY_HOST=203.0.113.10
CMO_PRIMARY_PORT=6379
CMO_BIND_ADDRESS=203.0.113.11
CMO_ANNOUNCE_IP=203.0.113.11
```

Replication authenticates as the admin user. The app user cannot `SYNC`.

Sentinel is a second unit. Copy the environment to `/etc/cache-me-outside/sentinel.environment` with `CMO_ROLE=sentinel`, `CMO_PORT=26379`, `CMO_PRIMARY_HOST` set to the current primary, and the same admin password the data nodes use. Then `systemctl enable --now cache-me-outside-sentinel.service`. Quorum and timing use the same variable names as the container (`CMO_SENTINEL_QUORUM`, `CMO_SENTINEL_DOWN_AFTER_MS`, `CMO_SENTINEL_FAILOVER_TIMEOUT`).

Cluster node:

```
CMO_ROLE=cluster
CMO_CLUSTER_ENABLED=yes
CMO_BIND_ADDRESS=203.0.113.10
CMO_ANNOUNCE_IP=203.0.113.10
CMO_ANNOUNCE_PORT=6379
CMO_ANNOUNCE_BUS_PORT=16379
```

Form the cluster from any node that can resolve the others, with `valkey-cli --cluster create` as the admin user. Adding a node later is `valkey-cli --cluster add-node` and, for a new primary, `--cluster rebalance --cluster-use-empty-primaries`. Open both the client port and the bus port (client port + 10000) between nodes.

## Cloud-init

`packaging/cloud-init/user-data.example.yaml` is a Debian 12 snippet: it writes `/etc/cache-me-outside/environment` and enables the unit. Install the `.deb` in the image (or a Proxmox template) before first boot. Replace the passwords in the snippet you actually feed to the VM. Leave the role block you want and delete the other commented lines so a later reader does not turn a replica into a cluster node by uncommenting both.

## Ansible

`packaging/ansible/` is an optional role, not an inventory of any real network.

```bash
cd packaging/ansible
ansible-playbook -i /path/to/your-inventory site.yml
```

`inventory.example.ini` shows the shape with documentation addresses. Keep the real inventory and the password vars (`cmo_admin_password`, `cmo_app_password`) outside the repo. The role refuses `0.0.0.0` and placeholder passwords. `cmo_deb_path` points at a built package on the target, or leave it empty when the package is already installed.

## Mixed with containers and Kubernetes

A node joins a cluster or a replication group by address, not by install method.

- A container started with `./up.sh node` publishes `CMO_BIND_ADDRESS` and announces `CMO_ANNOUNCE_IP`.
- A VM announces `CMO_ANNOUNCE_IP` and binds that address plus loopback.
- A pod announces its in-cluster DNS name by default. That name is useless to a VM outside the cluster. To join VMs, set `cluster.announce.mode` to `ip` and enable `hostPort` on one address (`hostIP`, never `0.0.0.0`). The chart then announces the node's host IP and the published client and bus ports. The pod IP is not assumed to be routable.

Use the same admin and app passwords on every member. The app user stays blocked from `@admin` and `@dangerous` on each of them.
