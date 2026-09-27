#!/usr/bin/env bash
# Start a 3-primary cluster, run the shared smoke checks, add a 4th primary,
# rebalance, confirm the keys are still there and slots moved, then drain the
# 4th node and confirm the keys again.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

export CMO_CLUSTER_PRIMARIES="${CMO_CLUSTER_PRIMARIES:-3}"
export CMO_CLUSTER_REPLICAS="${CMO_CLUSTER_REPLICAS:-0}"
export CMO_RESET_TOPOLOGY=1

./down.sh
./smoke.sh --generate-env cluster

cmo_load_env
export CMO_CLI_CLUSTER=1

count="${CMO_SCALE_KEYS:-80}"
for i in $(seq 1 "$count"); do
    cmo_app cmo-cluster-0 SET "cmo:scale:${i}" "v${i}" >/dev/null
done

./cluster-add.sh primary

# Slot ownership is gossiped after the reshard returns. A cluster-aware GET
# in that window can miss a key that is already on its new primary.
wait_stable() {
    # shellcheck disable=SC1091
    source .generated/state
    local names=() spec nodes_out i
    names=()
    for spec in "${nodes[@]}"; do
        # shellcheck disable=SC2086
        set -- $spec
        names+=("$1")
    done
    cmo_wait_cluster_agreement "${#names[@]}" "${names[@]}"
    for i in $(seq 1 30); do
        nodes_out="$(cmo_admin cmo-cluster-0 CLUSTER NODES)"
        if ! grep -q '\[' <<< "$nodes_out"; then
            return 0
        fi
        sleep 1
    done
    echo "scale: slots are still marked migrating" >&2
    return 1
}

read_keys() {
    local phase="$1" i got ok try
    for i in $(seq 1 "$count"); do
        ok=0
        got=""
        for try in $(seq 1 20); do
            got="$(cmo_app cmo-cluster-0 GET "cmo:scale:${i}" | tr -d '\r' || true)"
            if [[ "$got" == "v${i}" ]]; then
                ok=1
                break
            fi
            sleep 0.5
        done
        if [[ "$ok" -ne 1 ]]; then
            echo "scale: key cmo:scale:${i} is '${got}' after ${phase}" >&2
            cmo_admin cmo-cluster-0 CLUSTER NODES >&2 || true
            exit 1
        fi
    done
}

wait_stable

masters="$(cmo_admin cmo-cluster-0 CLUSTER NODES | awk '$3 ~ /master/ { print }')"
master_count="$(printf '%s\n' "$masters" | awk 'NF { c++ } END { print c+0 }')"
[[ "$master_count" == "4" ]] || {
    echo "scale: expected 4 primaries, found ${master_count}" >&2
    exit 1
}

small="$(printf '%s\n' "$masters" | awk '
    {
        slots = 0
        for (i = 9; i <= NF; i++) {
            if ($i ~ /^[0-9]+-[0-9]+$/) {
                split($i, r, "-")
                slots += r[2] - r[1] + 1
            } else if ($i ~ /^[0-9]+$/) slots++
        }
        if (slots < 1000) print slots
    }')"
if [[ -n "$small" ]]; then
    echo "scale: a primary owns fewer than 1000 slots after rebalance" >&2
    printf '%s\n' "$masters" >&2
    exit 1
fi

read_keys rebalance

./cluster-remove.sh cmo-cluster-3

masters="$(cmo_admin cmo-cluster-0 CLUSTER NODES | awk '$3 ~ /master/ { print }')"
master_count="$(printf '%s\n' "$masters" | awk 'NF { c++ } END { print c+0 }')"
[[ "$master_count" == "3" ]] || {
    echo "scale: expected 3 primaries after drain, found ${master_count}" >&2
    exit 1
}
if docker inspect cmo-cluster-3 >/dev/null 2>&1; then
    echo "scale: cmo-cluster-3 is still present" >&2
    exit 1
fi
wait_stable
read_keys drain

echo "scale: ok (4th primary joined, slots spread, keys survived add and drain)"
