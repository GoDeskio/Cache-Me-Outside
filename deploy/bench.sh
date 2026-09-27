#!/usr/bin/env bash
# Benchmark a running Cache-Me-Outside node and a stock Valkey container.
# Writes deploy/results/bench-<utc>.txt. Does not print passwords.
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
    echo "Missing deploy/.env. Start the stack with ./up.sh first." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

: "${CMO_ADMIN_USER:=admin}"
: "${CMO_APP_USER:=app}"
: "${CMO_PORT:=6379}"
: "${CMO_BIND_ADDRESS:=127.0.0.1}"
: "${CMO_HOST_PORT:=6379}"
: "${CMO_MAXMEMORY:=256mb}"
: "${CMO_MAXMEMORY_POLICY:=allkeys-lru}"

requests="${CMO_BENCH_REQUESTS:-100000}"
clients="${CMO_BENCH_CLIENTS:-20}"
upstream_name="cmo-bench-upstream"
upstream_port="16379"

mkdir -p results
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="results/bench-${stamp}.txt"

cleanup() {
    docker rm -f "$upstream_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! docker inspect cache-me-outside >/dev/null 2>&1; then
    echo "cache-me-outside is not running. Start it with ./up.sh." >&2
    exit 1
fi

info="$(docker exec cache-me-outside valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning INFO server)"
version="$(printf '%s\n' "$info" | awk -F: '/^valkey_version:/{gsub(/\r/, "", $2); print $2}')"
marker="$(printf '%s\n' "$info" | awk -F: '/^cmo_version:/{gsub(/\r/, "", $2); print $2}')"

resolve_upstream() {
    local candidate
    local candidates=()
    candidates+=("valkey/valkey:${version}")
    case "$version" in
        255.*) candidates+=("valkey/valkey:unstable") ;;
    esac
    candidates+=("valkey/valkey:8")
    for candidate in "${candidates[@]}"; do
        if docker pull "$candidate" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

upstream_image="$(resolve_upstream)" || {
    echo "Could not pull a stock Valkey image for version ${version}." >&2
    exit 1
}

note="same published tag as valkey_version"
if [[ "$upstream_image" != "valkey/valkey:${version}" ]]; then
    note="valkey/valkey:${version} is not published; compared with ${upstream_image}"
fi

# Inside the container the server listens on the Docker network. The host
# mapping for the stock container stays on 127.0.0.1.
docker rm -f "$upstream_name" >/dev/null 2>&1 || true
docker run -d --name "$upstream_name" \
    --network cache-me-outside \
    -p "127.0.0.1:${upstream_port}:6379" \
    "$upstream_image" \
    --requirepass "$CMO_APP_PASSWORD" \
    --protected-mode yes \
    --bind 0.0.0.0 \
    --maxmemory "$CMO_MAXMEMORY" \
    --maxmemory-policy "$CMO_MAXMEMORY_POLICY" \
    --save "" \
    --appendonly no >/dev/null

ready=0
for _i in $(seq 1 30); do
    if docker exec "$upstream_name" valkey-cli -a "$CMO_APP_PASSWORD" --no-auth-warning PING 2>/dev/null | grep -q PONG; then
        ready=1
        break
    fi
    sleep 1
done
[[ "$ready" -eq 1 ]] || {
    echo "Stock Valkey container did not start." >&2
    docker logs "$upstream_name" >&2 || true
    exit 1
}

{
    echo "Cache-Me-Outside benchmark ${stamp}"
    echo "cmo_version: ${marker}"
    echo "valkey_version: ${version}"
    echo "upstream_image: ${upstream_image}"
    echo "upstream_note: ${note}"
    echo "requests: ${requests}"
    echo "clients: ${clients}"
    echo "payload_bytes: 64"
    echo "tests: set,get"
    echo
    echo "Each valkey-benchmark run is inside that server's container, against 127.0.0.1."
    echo "Cache-Me-Outside is the compose deployment (AOF everysec, RDB, ACL app user)."
    echo "Stock Valkey uses the same maxmemory and policy, with AUTH on the default user,"
    echo "and with AOF and RDB snapshots disabled so the comparison is mostly command throughput."
    echo
    echo "===== cache-me-outside ====="
} | tee "$out"

docker exec cache-me-outside valkey-benchmark \
    -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" \
    -t set,get -n "$requests" -c "$clients" -d 64 --threads 2 | tee -a "$out"

{
    echo
    echo "===== stock valkey (${upstream_image}) ====="
} | tee -a "$out"

docker exec "$upstream_name" valkey-benchmark \
    -h 127.0.0.1 -p 6379 \
    -a "$CMO_APP_PASSWORD" \
    -t set,get -n "$requests" -c "$clients" -d 64 --threads 2 | tee -a "$out"

{
    echo
    echo "===== memtier_benchmark ====="
} | tee -a "$out"

if command -v memtier_benchmark >/dev/null 2>&1; then
    memtier_benchmark \
        -s "$CMO_BIND_ADDRESS" -p "$CMO_HOST_PORT" \
        --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" \
        --hide-histogram -n 10000 -c 10 -t 2 --ratio 1:1 | tee -a "$out"
else
    echo "memtier_benchmark is not installed; skipped." | tee -a "$out"
fi

echo "bench: wrote ${out}"
