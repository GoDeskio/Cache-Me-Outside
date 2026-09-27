# Cache-Me-Outside

Cache-Me-Outside is GoDesk's fork of [Valkey](https://github.com/valkey-io/valkey) `unstable`. It is the cache we build and run on the home-lab server. The server, protocol, and command names are Valkey's, so existing Redis and Valkey clients work without a new wire protocol.

`INFO server` includes `cmo_version`, the Valkey version plus `-cmo`. `valkey_version` stays numeric.

Valkey and the Redis code it inherited stay under the BSD 3-Clause License. See [COPYING](../../COPYING) and [NOTICE](../../NOTICE).

## Docs

- [Build](build.md)
- [Deploy](deploy.md)
- [Config](config.md)
- [Security defaults](security.md)
- [Benchmarking](benchmarking.md)
- [Upstream sync](upstream-sync.md)
- [Roadmap](roadmap.md)

## What this fork changes

The fork is additive. New files live under `deploy/`, `docs/cache-me-outside/`, and `.github/workflows/cmo-ci.yml`. The server change is the `cmo_version` field in `src/server.c` and `src/cmo_version.h`. Binaries stay `valkey-server`, `valkey-cli`, and `valkey-benchmark`. `make install` still creates the `redis-*` symlinks.
