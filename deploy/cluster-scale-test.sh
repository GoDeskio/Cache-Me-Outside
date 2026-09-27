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

for i in $(seq 1 "$count"); do
    got="$(cmo_app cmo-cluster-0 GET "cmo:scale:${i}" | tr -d '\r')"
    [[ "$got" == "v${i}" ]] || {
        echo "scale: key cmo:scale:${i} is '${got}' after rebalance" >&2
        exit 1
    }
done

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
for i in $(seq 1 "$count"); do
    got="$(cmo_app cmo-cluster-0 GET "cmo:scale:${i}" | tr -d '\r')"
    [[ "$got" == "v${i}" ]] || {
        echo "scale: key cmo:scale:${i} is '${got}' after drain" >&2
        exit 1
    }
done

echo "scale: ok (4th primary joined, slots spread, keys survived add and drain)"
