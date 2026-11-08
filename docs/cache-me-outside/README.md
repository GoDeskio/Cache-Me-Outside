# Cache-Me-Outside

Cache-Me-Outside is GoDesk's fork of [Valkey](https://github.com/valkey-io/valkey) `unstable`. It is the cache we build and run on the home-lab server. The server, protocol, and command names are Valkey's, so existing Redis and Valkey clients work without a new wire protocol.

`INFO server` includes `cmo_version`, the Valkey version plus `-cmo`. `valkey_version` stays numeric.

Valkey and the Redis code it inherited stay under the BSD 3-Clause License. See [COPYING](../../COPYING) and [NOTICE](../../NOTICE).

## Docs

- [Build](build.md)
- [Deploy](deploy.md)
- [Config](config.md)
- [Scaling](scaling.md)
- [Kubernetes](kubernetes.md)
- [Virtual machines](virtual-machines.md)
- [Deployment targets](targets.md)
- [Security defaults](security.md)
- [Benchmarking](benchmarking.md)
- [Upstream sync](upstream-sync.md)
- [Roadmap](roadmap.md)
- [Warm restart](warm-restart.md)
- [DRAM + flash hybrid storage](hybrid-storage.md)
- [TTL-grouped storage](ttl-segments.md)
- [Management API and site](management-api.md)
- [Adopting the cache from another GoDesk app](../../INTEGRATION.md)

## What this fork changes

The fork is additive. New files live under `deploy/`, `packaging/`, `docs/cache-me-outside/`, and `.github/workflows/cmo-ci.yml`. The server reports `cmo_version`. When `cmo-warm-enabled` is on, a clean shutdown writes a checkpoint that the next process loads if RDB and AOF did not. When `cmo-hybrid-enabled` is on, large strings spill to a flash log. When `cmo-ttl-segments` is on, keys that expire in the same time bucket are deleted together. All three are off unless configured. Binaries stay `valkey-server`, `valkey-cli`, and `valkey-benchmark`. `make install` still creates the `redis-*` symlinks. Standalone, Sentinel, and cluster layouts are selected with `deploy/up.sh` and do not rename those binaries. A `.deb` and a Helm chart install the same binaries on a VM or a Kubernetes cluster.
