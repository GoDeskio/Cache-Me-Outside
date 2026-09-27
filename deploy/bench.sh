#!/usr/bin/env bash
# Benchmark a running Cache-Me-Outside node and a stock Valkey container.
# Writes ${CMO_BENCH_OUT_DIR:-deploy/results}/bench-<utc>.txt. Does not print passwords.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh
cmo_load_env

requests="${CMO_BENCH_REQUESTS:-100000}"
clients="${CMO_BENCH_CLIENTS:-20}"
upstream_name="cmo-bench-upstream"
upstream_port="16379"
bench_user="$CMO_APP_USER"
bench_pass="$CMO_APP_PASSWORD"
if [[ "${CMO_BENCH_USER:-app}" == "admin" ]]; then
    bench_user="$CMO_ADMIN_USER"
    bench_pass="$CMO_ADMIN_PASSWORD"
fi

out_dir="${CMO_BENCH_OUT_DIR:-results}"
case "$out_dir" in
    /*) ;;
    *) out_dir="$(pwd)/${out_dir}" ;;
esac
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${out_dir}/bench-${stamp}.txt"

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

config_value() {
    local container="$1" port="$2" user="$3" pass="$4" key="$5"
    docker exec "$container" valkey-cli -h 127.0.0.1 -p "$port" \
        --user "$user" -a "$pass" --no-auth-warning CONFIG GET "$key" \
        | awk 'NR==2 { gsub(/\r/, "", $0); print }'
}

cmo_save="$(config_value cache-me-outside "$CMO_PORT" "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" save || true)"
cmo_aof="$(config_value cache-me-outside "$CMO_PORT" "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" appendonly || true)"
cmo_fsync="$(config_value cache-me-outside "$CMO_PORT" "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" appendfsync || true)"

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

# Match persistence. ACL is not the same: stock uses requirepass on the
# default user, which can run CONFIG. The report says so.
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
    --appendonly yes \
    --appendfsync everysec \
    --save "3600 1" \
    --save "300 100" \
    --save "60 10000" >/dev/null

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

stock_save="$(config_value "$upstream_name" 6379 default "$CMO_APP_PASSWORD" save || true)"
stock_aof="$(config_value "$upstream_name" 6379 default "$CMO_APP_PASSWORD" appendonly || true)"
stock_fsync="$(config_value "$upstream_name" 6379 default "$CMO_APP_PASSWORD" appendfsync || true)"

run_bench() {
    local container="$1" port="$2" user="$3" pass="$4"
    # The app user cannot CONFIG. valkey-benchmark warns and continues.
    # Drop that one line. The save/appendonly values above were read as admin.
    docker exec "$container" valkey-benchmark \
        -h 127.0.0.1 -p "$port" \
        --user "$user" -a "$pass" \
        -t set,get -n "$requests" -c "$clients" -d 64 --threads 2 \
        2>&1 | sed '/^WARNING: Could not fetch server CONFIG$/d'
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
    echo "bench_user: ${bench_user}"
    echo "cmo_appendonly: ${cmo_aof}"
    echo "cmo_appendfsync: ${cmo_fsync}"
    echo "cmo_save: ${cmo_save}"
    echo "stock_appendonly: ${stock_aof}"
    echo "stock_appendfsync: ${stock_fsync}"
    echo "stock_save: ${stock_save}"
    echo
    echo "Each valkey-benchmark run is inside that server's container, against 127.0.0.1."
    echo "Persistence matches: AOF everysec and the same RDB save rules."
    echo "ACL does not: Cache-Me-Outside uses the ${bench_user} user. Stock Valkey uses"
    echo "requirepass on the default user, which can run every command including CONFIG."
    echo "Set CMO_BENCH_USER=admin to benchmark Cache-Me-Outside as the admin user so the"
    echo "client can fetch CONFIG itself. The default stays the app user."
    echo
    echo "===== cache-me-outside ====="
} | tee "$out"

run_bench cache-me-outside "$CMO_PORT" "$bench_user" "$bench_pass" | tee -a "$out"

{
    echo
    echo "===== stock valkey (${upstream_image}) ====="
} | tee -a "$out"

run_bench "$upstream_name" 6379 default "$CMO_APP_PASSWORD" | tee -a "$out"

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
