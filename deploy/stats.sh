#!/usr/bin/env bash
# Health numbers for the standalone node (plan items 50 and 51): hit rate,
# memory, ops/s, connected clients, evictions, latency percentiles, and the
# slowest recent commands.
#
#   ./stats.sh            human summary
#   ./stats.sh --json     one JSON object (for a dashboard or exporter)
#   ./stats.sh --slowlog  last 10 SLOWLOG entries as JSON
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source ./lib.sh

# Reads INFO text on stdin, prints key=value metrics. Pure, so it is testable.
cmo_stats_from_info() {
    tr -d '\r' | awk -F: '
        /^(keyspace_hits|keyspace_misses|used_memory|maxmemory|instantaneous_ops_per_sec|connected_clients|evicted_keys|expired_keys|uptime_in_seconds):/ { v[$1]=$2 }
        /^latency_percentiles_usec_[a-z|]+:/ {
            cmd=$1; sub(/^latency_percentiles_usec_/, "", cmd)
            if (cmd == "get" || cmd == "set") {
                n=split($2, parts, ","); for (i=1;i<=n;i++){ split(parts[i], kv, "="); if (kv[1]=="p99") v[cmd "_p99_usec"]=kv[2] }
            }
        }
        END {
            h=v["keyspace_hits"]+0; m=v["keyspace_misses"]+0
            printf "hit_rate=%s\n", (h+m>0) ? sprintf("%.4f", h/(h+m)) : "null"
            printf "used_memory=%d\nmaxmemory=%d\n", v["used_memory"], v["maxmemory"]
            printf "memory_ratio=%s\n", (v["maxmemory"]+0>0) ? sprintf("%.4f", v["used_memory"]/v["maxmemory"]) : "null"
            printf "ops_per_sec=%d\nconnected_clients=%d\nevicted_keys=%d\nexpired_keys=%d\nuptime_seconds=%d\n", v["instantaneous_ops_per_sec"], v["connected_clients"], v["evicted_keys"], v["expired_keys"], v["uptime_in_seconds"]
            printf "get_p99_usec=%s\nset_p99_usec=%s\n", ("get_p99_usec" in v) ? v["get_p99_usec"]+0 : "null", ("set_p99_usec" in v) ? v["set_p99_usec"]+0 : "null"
        }'
}

cmo_stats_json() {
    awk -F= 'BEGIN{printf "{"} {printf "%s\"%s\":%s", (NR>1?",":""), $1, $2} END{print "}"}'
}

if [[ "${CMO_STATS_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

cmo_load_env
container="$(cmo_standalone_name)"
case "${1:-}" in
    "") cmo_admin "$container" INFO everything | cmo_stats_from_info ;;
    --json) cmo_admin "$container" INFO everything | cmo_stats_from_info | cmo_stats_json ;;
    # Entries include arguments (Valkey truncates them); admin-only output.
    --slowlog) cmo_admin "$container" --json SLOWLOG GET 10 | tr -d '\r' ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
esac
