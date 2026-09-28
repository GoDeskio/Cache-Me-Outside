# Security defaults

This is a home-lab cache on a LAN, not an Internet-facing service. The defaults assume the Docker host is reachable by people and devices you trust, and that the port is still authenticated.

## Authentication

The built-in `default` user is reset at start: disabled, no password, no `nopass` flag, no commands. New connections are unauthenticated. `PING` without `AUTH` returns `NOAUTH`.

`protected-mode yes` stays on. Valkey's protected mode blocks non-local clients when the default user has `nopass`. Resetting that user clears `nopass`, so clients on the Docker bridge can connect, and they still cannot run commands until they authenticate.

There is no password in git. `deploy/cache-me-outside.env.example` contains the text `replace-with`, and the entrypoint refuses to start if a password is missing, shorter than 16 characters, a placeholder, or shared by both users.

## Users

| User | Commands |
| --- | --- |
| `default` | Disabled |
| app (`CMO_APP_USER`) | `+@all -@dangerous -@admin`, plus an explicit deny for `FLUSHALL`, `FLUSHDB`, `DEBUG`, `CONFIG`, `KEYS`, `SHUTDOWN`, module load, ACL changes, replication, migrate, restore, sort, failover, `BGSAVE`, `BGREWRITEAOF`, `SAVE`, `MONITOR`, `SYNC`, and `PSYNC` |
| admin (`CMO_ADMIN_USER`) | `+@all` |

The app user can `SET`, `GET`, `DEL`, `PING`, `SCAN`, and the usual structure commands. It cannot read `INFO` (`INFO` is in `@dangerous`) and cannot change config. Use the admin user for `INFO`, `CONFIG`, snapshots, replication, and cluster administration.

On Sentinel processes the app user is also allowed a short list of read-only discovery commands (`SENTINEL GET-PRIMARY-ADDR-BY-NAME` and the replica/sentinel listings) so a sentinel-aware client can find the primary. Those command names are not registered on data nodes, so the data-node ACL does not list them. `SENTINEL FAILOVER` and the other Sentinel admin subcommands stay denied. Cluster clients can run `CLUSTER SLOTS` and `CLUSTER NODES` (those are not admin commands). `CLUSTER MEET`, `CLUSTER SETSLOT`, and the other admin cluster commands stay denied.

Replicas and cluster nodes authenticate replication as the admin user (`masteruser` / `masterauth`). That password stays in the container environment and in a mode `0600` file under `/tmp`, not in the image and not in git.

`enable-debug-command` stays at its Valkey default, `no`, so `DEBUG` is refused for every user, including admin. The app ACL also removes `DEBUG`, which still applies if an operator later turns the command on.

Give application containers the app user only. Keep the admin password for operators.

## Network

- Host publish address defaults to `127.0.0.1`. `deploy/up.sh` exits if it is `0.0.0.0`, `::`, or `*`.
- Inside the container the process binds `0.0.0.0` so the Docker published port and an optional `proxy-net` attachment work. That bind is not a host bind.
- The Compose service sets `no-new-privileges` and a memory cap.
- The server process runs as uid 999, not root.

Do not put this port on the public Internet. If you set `CMO_BIND_ADDRESS` to a LAN IP, clients on that LAN can attempt `AUTH`. Passwords still have to hold.

## What is not in this setup

TLS is not enabled. There is one app user, not one user per service. See [roadmap](roadmap.md) for proposals that are not implemented.
