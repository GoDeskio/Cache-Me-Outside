# Deploy

Single node, Docker Compose, Linux containers. This matches Docker Desktop on Windows as well as a Linux home-lab host.

## One-time setup

```bash
cd deploy
umask 077
cp cache-me-outside.env.example .env
chmod 600 .env
```

Edit `.env` and replace both passwords. They must differ, be at least 16 characters, and use only letters, digits, and `_ . / + = @ -`. `deploy/.env` is gitignored. Do not commit it.

If the file lives outside the repo, point the scripts at it. Compose reads the same path for interpolation and for the container environment, and the path is `required: false` so a missing file does not fail `compose config` before the scripts tell you what to copy.

```bash
export CMO_ENV_FILE=/path/to/vault/cache-me-outside.env
./up.sh
```

`CMO_BIND_ADDRESS` defaults to `127.0.0.1`. That is the address on the **host**. Leave it there when only local clients connect. To reach the cache from other machines on the LAN, set it to that host's LAN address (one address, not every interface). `deploy/up.sh` refuses `0.0.0.0`, `::`, and `*`.

On Docker Desktop, `127.0.0.1` is the Windows or macOS localhost. Publishing `0.0.0.0` would expose the port on every host interface, so that is not the default and the start script rejects it.

## Start

```bash
./up.sh
```

That builds the image from this source, starts the container, and waits until the health check passes. The health check authenticates as the app user and expects `PONG`.

Other containers on the Compose network `cache-me-outside` can use the DNS name `cache-me-outside` and port 6379.

Data is the named volume `cache-me-outside-data`, mounted at `/data` (AOF and RDB).

The Compose project, network, and container prefix are `CMO_PROJECT`, `CMO_NETWORK`, and `CMO_NAME_PREFIX`. All three default to `cache-me-outside`. Generated compose files for Sentinel and cluster live in `deploy/.generated/<project>/`, so a second project does not share that state. `CMO_SUBNET` (for example `203.0.113.0/24` in documentation) pins the network this project creates. Leave it unset unless Docker's default pools are used up. A pool such as `192.168.0.0/20` can overlap the LAN and cut containers off from it.

## Optional proxy network

If other stacks should reach the cache by name, create the external network once and add the override file:

```bash
docker network create proxy-net
docker compose -f docker-compose.yml -f docker-compose.proxy-net.yml up -d
```

`deploy/up.sh` does not attach `proxy-net`, so a missing network does not block a normal start. The alias on that network is `cache-me-outside`. Set `CMO_NETWORK_ALIAS` to another project-specific name if you need one. `redis` and `valkey` are rejected, because those names take over DNS for every other stack on the shared network. Kubernetes Service names follow the Helm release (`<release>-cmo`) and are not `redis` or `valkey` either.

## Other topologies

`./up.sh` is standalone. `./up.sh sentinel` and `./up.sh cluster` render a compose file under `deploy/.generated/` (gitignored) from the counts in `.env`. `./up.sh node` is one process for a machine that will join other hosts, and it requires `CMO_ANNOUNCE_IP`. Details, including how to add and remove cluster nodes, are in [scaling](scaling.md). Kubernetes is the Helm chart in [kubernetes](kubernetes.md). A VM without Docker is the `.deb` in [virtual machines](virtual-machines.md). The [target matrix](targets.md) lists which CI job covers each one.

## Stop

```bash
./down.sh                 # stop containers, keep volumes
./down.sh --volumes       # also delete this project's volumes
./down.sh --remove-orphans
```

`./down.sh` stops the containers for the current `CMO_PROJECT` only, and deletes `deploy/.generated/<project>/`. Volumes stay unless you pass `--volumes`. Deleting volumes for the default project (`cache-me-outside`, or `CMO_PRODUCTION_PROJECT` when that was filled in because `CMO_PROJECT` was unset) also requires `--i-know` or an explicit `CMO_PROJECT`. `--remove-orphans` is not passed unless you ask for it. The script does not remove a container whose name belongs to a different prefix. `deploy/.env` is left in place. Test scripts call `./down.sh --volumes` only after selecting `cmo-test`, and they refuse the default project unless `--i-know` is passed. `cluster-remove.sh` deletes the drained container by name. It does not pass `--remove-orphans`, which would also delete a standalone container in the same project.
