# Deployment targets

Cache-Me-Outside is the same Valkey build in each target. Clients keep using the Valkey and Redis protocols. Passwords are never in the image, the chart, or the package.

| Target | How you start it | Topologies | What CI checks |
| --- | --- | --- | --- |
| Docker Compose on Linux, or Docker Desktop with Linux containers | `deploy/up.sh` | standalone, Sentinel, cluster, one node for another host | image build, smoke, Sentinel failover, cluster scale-out |
| Kubernetes (k3s, kind, and other clusters that run Helm) | `deploy/helm/cache-me-outside` | standalone, Sentinel, cluster | helm lint, kubeconform, kind standalone smoke, kind cluster scale-out |
| Debian or Ubuntu VM, including a Debian 12 cloud-init image | `packaging/build-deb.sh` and systemd | standalone, replica, Sentinel, cluster node | `.deb` install and native smoke in a Debian 12 container |

Ansible under `packaging/ansible/` is an optional way to push the `.deb` and the environment file onto several VMs. It is not a separate runtime.

## What is shared

- ACL: `default` disabled, an admin user, an app user without dangerous or admin commands
- `protected-mode yes`
- AOF everysec and RDB snapshots
- `maxmemory` and `allkeys-lru` unless you change them
- Host exposure is one address. Compose refuses `0.0.0.0`. The VM unit refuses it. The chart refuses a wildcard `hostPort`
- `cmo_version` in `INFO server`

## What is different

Compose publishes a host port and the process binds `0.0.0.0` inside the container network namespace. On a VM the process bind is the host bind, plus loopback. In Kubernetes the process is reached through Services, and host ports stay off unless you are joining machines outside the cluster.

An HorizontalPodAutoscaler is not a target. See [kubernetes](kubernetes.md).

## Picking one

Use Compose when the cache lives on one machine you already run with Docker. Use Sentinel when that machine should survive a process crash and you want read replicas. Use cluster when one process cannot hold the working set. Use a VM when the host should not run Docker. Use Kubernetes when the cache should live in the same cluster as the apps, and use the VM package or `./up.sh node` for members that stay outside that cluster. [Scaling](scaling.md) is the capacity side of that choice. [Virtual machines](virtual-machines.md) covers mixed membership.
