#!/bin/sh
# Start Cache-Me-Outside on a VM or bare-metal host.
# The process bind is the host bind. 0.0.0.0 is refused.
# systemd passes EnvironmentFile variables in before this runs.
set -eu

: "${CMO_BIND_ADDRESS:=127.0.0.1}"

refuse_wildcard() {
    case "$1" in
        "" | 0.0.0.0 | "::" | "*" | "[::]" | "0.0.0.0/0")
            echo "cache-me-outside: refusing wildcard address in $2 ($1)" >&2
            exit 1
            ;;
    esac
}

refuse_wildcard "$CMO_BIND_ADDRESS" CMO_BIND_ADDRESS
if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
    refuse_wildcard "$CMO_ANNOUNCE_IP" CMO_ANNOUNCE_IP
fi

# Local admin shutdown and health checks use 127.0.0.1 even when the
# published address is a single reachable NIC.
if [ "$CMO_BIND_ADDRESS" = "127.0.0.1" ]; then
    export CMO_CONTAINER_BIND="127.0.0.1"
else
    export CMO_CONTAINER_BIND="127.0.0.1 ${CMO_BIND_ADDRESS}"
fi

export CMO_DATA_DIR="${CMO_DATA_DIR:-/var/lib/cache-me-outside}"
export CMO_RUNTIME_DIR="${CMO_RUNTIME_DIR:-/run/cache-me-outside}"
mkdir -p "$CMO_DATA_DIR" "$CMO_RUNTIME_DIR"
chmod 750 "$CMO_DATA_DIR" "$CMO_RUNTIME_DIR" || true

exec /usr/lib/cache-me-outside/docker-entrypoint.sh "$@"
