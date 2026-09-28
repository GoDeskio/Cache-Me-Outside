#!/usr/bin/env bash
# Raise maxmemory on a live data node without restarting it.
# The container memory limit is not changed. The new value must be greater
# than the current one and at most half the live cgroup limit, so a fork
# (AOF rewrite or RDB) still has room. deploy/.env is updated when every
# targeted node changes, so the next recreate keeps the value. A restart of
# an already-created container keeps the environment it was created with.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh
cmo_load_env

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "Usage: ./scale-memory.sh <maxmemory> [container|--all]" >&2
    echo "Example: ./scale-memory.sh 384mb cache-me-outside" >&2
    exit 1
fi

new_raw="$1"
target="${2:-}"
new_bytes="$(cmo_mem_to_bytes "$new_raw")"

if [[ -z "$target" ]]; then
    if docker inspect cache-me-outside >/dev/null 2>&1; then
        target="cache-me-outside"
    else
        target="--all"
    fi
fi

containers=()
if [[ "$target" == "--all" ]]; then
    if [[ -f .generated/state ]]; then
        # shellcheck disable=SC1091
        source .generated/state
        for spec in "${nodes[@]}"; do
            # shellcheck disable=SC2086
            set -- $spec
            containers+=("$1")
        done
    elif docker inspect cache-me-outside >/dev/null 2>&1; then
        containers+=(cache-me-outside)
    else
        echo "No data nodes are running." >&2
        exit 1
    fi
else
    case "$target" in
        cmo-sentinel-*)
            echo "Sentinel processes are not data nodes." >&2
            exit 1
            ;;
    esac
    containers+=("$target")
fi

failures=0
for container in "${containers[@]}"; do
    if ! docker inspect "$container" >/dev/null 2>&1; then
        echo "${container}: not running" >&2
        failures=1
        continue
    fi
    current="$(cmo_admin "$container" CONFIG GET maxmemory | awk 'NR==2 { gsub(/\r/, "", $1); print $1 }')"
    if [[ -z "$current" || "$current" == *ERR* || "$current" == *NOPERM* ]]; then
        echo "${container}: admin CONFIG GET maxmemory failed: ${current:-empty}" >&2
        failures=1
        continue
    fi
    if ((new_bytes <= current)); then
        echo "${container}: refusing to lower or keep maxmemory (${current} bytes -> ${new_bytes} bytes)." >&2
        failures=1
        continue
    fi
    limit="$(docker inspect --format '{{.HostConfig.Memory}}' "$container")"
    if [[ "$limit" =~ ^[0-9]+$ ]] && ((limit > 0)); then
        if ((new_bytes * 2 > limit)); then
            echo "${container}: ${new_raw} is more than half the container limit (${limit} bytes)." >&2
            echo "Raise CMO_CONTAINER_MEMORY and recreate the container before raising maxmemory this far." >&2
            failures=1
            continue
        fi
    else
        echo "${container}: warning: no memory limit is set; the 2x headroom check was skipped." >&2
    fi
    result="$(cmo_admin "$container" CONFIG SET maxmemory "$new_raw" | tr -d '\r')"
    if [[ "$result" != "OK" ]]; then
        echo "${container}: CONFIG SET failed: ${result}" >&2
        failures=1
        continue
    fi
    applied="$(cmo_admin "$container" CONFIG GET maxmemory | awk 'NR==2 { gsub(/\r/, "", $1); print $1 }')"
    if [[ "$applied" != "$new_bytes" ]]; then
        echo "${container}: maxmemory is ${applied}, expected ${new_bytes}" >&2
        failures=1
        continue
    fi
    echo "${container}: maxmemory ${current} -> ${applied} bytes"
done

if ((failures != 0)); then
    exit 1
fi

# One shared env file. Update it when the call covered every targeted node,
# including a single explicit container, so the next recreate does not revert.
env_path="$(cmo_env_path)"
if grep -q '^CMO_MAXMEMORY=' "$env_path"; then
    sed -i "s/^CMO_MAXMEMORY=.*/CMO_MAXMEMORY=${new_raw}/" "$env_path"
else
    echo "CMO_MAXMEMORY=${new_raw}" >> "$env_path"
fi
echo "Updated ${env_path} CMO_MAXMEMORY=${new_raw}. Recreate containers to keep it across a new process."
