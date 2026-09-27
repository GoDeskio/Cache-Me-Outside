# Build

## Local binary

From the repository root, the same way as upstream Valkey:

```bash
make -j"$(nproc)"
./src/valkey-server --version
```

`make install PREFIX=/usr/local` installs `valkey-*` and the `redis-*` compatibility symlinks. Do not rename those programs. Clients and scripts look them up by those names.

A fast subset of the upstream Tcl suite, the same one CI runs:

```bash
sudo apt-get install tcl tcl8.6 tclx
./runtest --dump-logs \
  --single unit/cmo-version \
  --single unit/auth \
  --single unit/acl \
  --single unit/protocol \
  --single unit/keyspace \
  --single unit/info
```

`tests/unit/cmo-version.tcl` checks that `cmo_version` is `<valkey_version>-cmo` and that `valkey_version` has no suffix.

## Container image

The Dockerfile compiles this tree. It does not download an upstream Valkey image for the runtime.

```bash
docker build -t cache-me-outside:local .
```

The build stage is Debian bookworm. The runtime stage copies the installed binaries, `gosu`, and `deploy/valkey.conf`. The entrypoint starts as root only long enough to make `/data` writable, then runs `valkey-server` as uid 999 (`valkey`).

`redis-server`, `redis-cli`, and `redis-benchmark` in the image are symlinks to the `valkey-*` binaries.

The image has no passwords baked in. `CMO_ADMIN_PASSWORD` and `CMO_APP_PASSWORD` are required at start and are written to `/tmp/cmo-users.acl`, which is not on the data volume.
