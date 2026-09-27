#!/usr/bin/env bash
# Start Cache-Me-Outside.
#   ./up.sh                  standalone (default)
#   ./up.sh sentinel         primary, replicas, and Sentinel
#   ./up.sh cluster          sharded cluster, then bootstrap slots
#   ./up.sh node             one node for a multi-host layout
# Refuses to publish a host port on every interface.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

topology="standalone"
case "${1:-}" in
    standalone | sentinel | cluster | node)
        topology="$1"
        shift
        ;;
esac
export CMO_TOPOLOGY="$topology"

cmo_load_env
cmo_refuse_wildcard_bind "${CMO_BIND_ADDRESS}" CMO_BIND_ADDRESS
cmo_refuse_generic_alias "${CMO_NETWORK_ALIAS:-cache-me-outside}"

host_port="${CMO_HOST_PORT}"
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

# Per-node overrides, when set, are checked the same way as the default.
while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    cmo_refuse_wildcard_bind "${!name}" "$name"
done < <(compgen -A variable | grep -E '^CMO_BIND_ADDRESS_' || true)

if [[ "$topology" == "node" ]]; then
    if [[ -z "${CMO_ANNOUNCE_IP:-}" ]]; then
        echo "up.sh node requires CMO_ANNOUNCE_IP (one address other hosts can reach)." >&2
        echo "Do not use 0.0.0.0." >&2
        exit 1
    fi
    cmo_refuse_wildcard_bind "${CMO_ANNOUNCE_IP}" CMO_ANNOUNCE_IP
    exec cmo_dc -f docker-compose.node.yml up -d --build --wait "$@"
fi

if [[ "$topology" == "sentinel" || "$topology" == "cluster" ]]; then
    ./render-topology.sh "$topology"
    cmo_dc -f .generated/compose.yml up -d --build --wait "$@"
    if [[ "$topology" == "cluster" ]]; then
        ./cluster-bootstrap.sh
    fi
    exit 0
fi

exec cmo_dc -f docker-compose.yml up -d --build --wait "$@"
