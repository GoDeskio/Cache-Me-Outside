#!/usr/bin/env bash
# Pick the eviction policy (plan item 47) on live data nodes, no restart.
#
#   ./eviction-policy.sh                 show the current policy
#   ./eviction-policy.sh --list          list choices with one-line advice
#   ./eviction-policy.sh <policy> [container|--all]
#
# deploy/.env CMO_MAXMEMORY_POLICY is updated after every targeted node
# accepts it, so a recreate keeps the choice.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source ./lib.sh

CMO_POLICIES=(allkeys-lru allkeys-lfu allkeys-random volatile-lru volatile-lfu volatile-random volatile-ttl noeviction)

cmo_policy_valid() {
    local p
    for p in "${CMO_POLICIES[@]}"; do [[ "$1" == "$p" ]] && return 0; done
    return 1
}

cmo_policy_advice() {
    case "$1" in
        allkeys-lru) echo "General cache: drop the least recently used key (default)." ;;
        allkeys-lfu) echo "Skewed traffic: keep popular keys, drop rarely used ones." ;;
        allkeys-random) echo "Uniform access: cheapest, evicts any key at random." ;;
        volatile-lru) echo "Mixed data: only keys with a TTL are evicted, least recent first." ;;
        volatile-lfu) echo "Mixed data: only keys with a TTL, least frequently used first." ;;
        volatile-random) echo "Mixed data: only keys with a TTL, at random." ;;
        volatile-ttl) echo "Expiring data: evict keys closest to expiry first." ;;
        noeviction) echo "Primary store: writes fail when full instead of losing data." ;;
    esac
}

# Rewrite or append KEY=VALUE in an env file.
cmo_env_set() {
    local file="$1" key="$2" value="$3"
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$file"
    fi
}

if [[ "${CMO_POLICY_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

if [[ "${1:-}" == "--list" ]]; then
    for p in "${CMO_POLICIES[@]}"; do printf '%-16s %s\n' "$p" "$(cmo_policy_advice "$p")"; done
    exit 0
fi

cmo_load_env
standalone="$(cmo_standalone_name)"
if [[ $# -eq 0 ]]; then
    cmo_admin "$standalone" CONFIG GET maxmemory-policy | awk 'NR==2 { gsub(/\r/, ""); print }'
    exit 0
fi

policy="$1"; target="${2:-}"
if ! cmo_policy_valid "$policy"; then
    echo "Unknown policy: ${policy}. Run ./eviction-policy.sh --list." >&2
    exit 1
fi
containers=()
if [[ -z "$target" || "$target" == "--all" ]] && [[ -f "$(cmo_state_file)" ]]; then
    # shellcheck disable=SC1090
    source "$(cmo_state_file)"
    # shellcheck disable=SC2154
    for spec in "${nodes[@]}"; do
        # shellcheck disable=SC2086
        set -- $spec
        containers+=("$1")
    done
elif [[ -z "$target" || "$target" == "--all" ]]; then
    containers+=("$standalone")
else
    case "$target" in *-sentinel-*) echo "Sentinel processes are not data nodes." >&2; exit 1 ;; esac
    containers+=("$target")
fi

failures=0
for container in "${containers[@]}"; do
    result="$(cmo_admin "$container" CONFIG SET maxmemory-policy "$policy" | tr -d '\r')"
    if [[ "$result" != "OK" ]]; then echo "${container}: CONFIG SET failed: ${result}" >&2; failures=1; continue; fi
    echo "${container}: maxmemory-policy -> ${policy}"
done
((failures == 0)) || exit 1
env_path="$(cmo_env_path)"
cmo_env_set "$env_path" CMO_MAXMEMORY_POLICY "$policy"
echo "Updated ${env_path} CMO_MAXMEMORY_POLICY=${policy}."
