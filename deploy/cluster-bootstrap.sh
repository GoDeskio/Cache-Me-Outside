#!/usr/bin/env bash
# Assign slots on a freshly started cluster. Safe to run again: an already
# healthy cluster is left alone. In-network nodes are read from
# deploy/.generated/state. For one node per host, set CMO_CLUSTER_NODES to a
# comma-separated list of announce addresses (host:port) and run this on a
# machine that can reach them.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh
cmo_load_env

addrs=()
runner=""

if [[ -n "${CMO_CLUSTER_NODES:-}" ]]; then
    IFS=',' read -r -a addrs <<< "$CMO_CLUSTER_NODES"
    replicas="${CMO_CLUSTER_REPLICAS}"
else
    if [[ ! -f .generated/state ]]; then
        echo "No cluster state. Start it with ./up.sh cluster, or set CMO_CLUSTER_NODES." >&2
        exit 1
    fi
    # shellcheck disable=SC1091
    source .generated/state
    if [[ "$topology" != "cluster" ]]; then
        echo "State is ${topology}, not cluster." >&2
        exit 1
    fi
    replicas="${cluster_replicas:-0}"
    for spec in "${nodes[@]}"; do
        # shellcheck disable=SC2086
        set -- $spec
        cmo_wait_healthy "$1"
        addrs+=("$1:6379")
        if [[ -z "$runner" ]]; then
            runner="$1"
        fi
    done
fi

if [[ "${#addrs[@]}" -lt 3 ]]; then
    echo "A cluster needs at least 3 nodes." >&2
    exit 1
fi

already_ok() {
    local info
    if [[ -n "$runner" ]]; then
        info="$(cmo_admin "$runner" CLUSTER INFO || true)"
    elif command -v valkey-cli >/dev/null 2>&1; then
        info="$(valkey-cli -h "${addrs[0]%%:*}" -p "${addrs[0]##*:}" --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning CLUSTER INFO || true)"
    else
        info="$(docker run --rm --network host --entrypoint valkey-cli cache-me-outside:local \
            -h "${addrs[0]%%:*}" -p "${addrs[0]##*:}" \
            --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning CLUSTER INFO || true)"
    fi
    grep -q 'cluster_state:ok' <<< "$info"
}

if already_ok; then
    echo "cluster: already formed"
    exit 0
fi

run_create() {
    if [[ -n "$runner" ]]; then
        cmo_cluster_mgr "$runner" create "${addrs[@]}" --cluster-replicas "$replicas" --cluster-yes
        return
    fi
    if command -v valkey-cli >/dev/null 2>&1; then
        valkey-cli --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning \
            --cluster create "${addrs[@]}" --cluster-replicas "$replicas" --cluster-yes
        return
    fi
    docker run --rm --network host --entrypoint valkey-cli cache-me-outside:local \
        --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning \
        --cluster create "${addrs[@]}" --cluster-replicas "$replicas" --cluster-yes
}

run_create

for _i in $(seq 1 30); do
    if already_ok; then
        echo "cluster: formed (${#addrs[@]} nodes, replicas-per-primary ${replicas})"
        exit 0
    fi
    sleep 1
done

echo "cluster did not reach cluster_state:ok" >&2
exit 1
