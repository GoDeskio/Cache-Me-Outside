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

`CMO_BIND_ADDRESS` defaults to `127.0.0.1`. That is the address on the **host**. Leave it there when only local clients connect. To reach the cache from other machines on the LAN, set it to that host's LAN address (one address, not every interface). `deploy/up.sh` refuses `0.0.0.0`, `::`, and `*`.

On Docker Desktop, `127.0.0.1` is the Windows or macOS localhost. Publishing `0.0.0.0` would expose the port on every host interface, so that is not the default and the start script rejects it.

## Start

```bash
./up.sh
```

That builds the image from this source, starts the container, and waits until the health check passes. The health check authenticates as the app user and expects `PONG`.

Other containers on the Compose network `cache-me-outside` can use the DNS name `cache-me-outside` and port 6379.

Data is the named volume `cache-me-outside-data`, mounted at `/data` (AOF and RDB).

## Optional proxy network

If other stacks should reach the cache by name, create the external network once and add the override file:

```bash
docker network create proxy-net
docker compose -f docker-compose.yml -f docker-compose.proxy-net.yml up -d
```

`deploy/up.sh` does not attach `proxy-net`, so a missing network does not block a normal start. On `proxy-net` the aliases are `cache-me-outside`, `valkey`, and `redis`.

## Stop

```bash
docker compose down
```

Add `-v` only when you mean to delete the data volume.
