#!/usr/bin/env bash
# Start the single-node Cache-Me-Outside stack.
# Refuses to publish the host port on every interface.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "Missing deploy/.env." >&2
    echo "Copy cache-me-outside.env.example to .env, replace both passwords, and chmod 600 .env." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

bind_address="${CMO_BIND_ADDRESS:-127.0.0.1}"
case "$bind_address" in
    "" | 0.0.0.0 | "::" | "*" | "[::]" | "0.0.0.0/0")
        echo "Refusing to publish Cache-Me-Outside on all host interfaces (${bind_address})." >&2
        echo "Set CMO_BIND_ADDRESS to 127.0.0.1 or one LAN address." >&2
        exit 1
        ;;
esac

host_port="${CMO_HOST_PORT:-6379}"
case "$host_port" in
    '' | *[!0-9]*)
        echo "CMO_HOST_PORT must be numeric." >&2
        exit 1
        ;;
esac
if ((host_port < 1 || host_port > 65535)); then
    echo "CMO_HOST_PORT is out of range." >&2
    exit 1
fi

exec docker compose up -d --build --wait "$@"
