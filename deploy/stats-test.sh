#!/usr/bin/env bash
# Offline test for stats.sh parsing: no container needed.
set -euo pipefail
cd "$(dirname "$0")"
CMO_STATS_LIB=1
# shellcheck source=stats.sh
source ./stats.sh
fail() { echo "FAIL: $*" >&2; exit 1; }
info=$'# Stats\r\nkeyspace_hits:900\r\nkeyspace_misses:100\r\ninstantaneous_ops_per_sec:42\r\nevicted_keys:3\r\nexpired_keys:7\r\n# Memory\r\nused_memory:1048576\r\nmaxmemory:4194304\r\n# Clients\r\nconnected_clients:5\r\nuptime_in_seconds:60\r\n# Latencystats\r\nlatency_percentiles_usec_get:p50=1.003,p99=12.031,p99.9=20.1\r\nlatency_percentiles_usec_set:p50=2,p99=30.5,p99.9=40\r\nlatency_percentiles_usec_getex:p99=999\r\n'
out="$(printf '%s' "$info" | cmo_stats_from_info)"
for want in hit_rate=0.9000 memory_ratio=0.2500 ops_per_sec=42 connected_clients=5 evicted_keys=3 get_p99_usec=12.031 set_p99_usec=30.5; do
    grep -qx "$want" <<<"$out" || fail "missing ${want} in: ${out}"
done
empty="$(printf 'maxmemory:0\r\n' | cmo_stats_from_info)"
grep -qx hit_rate=null <<<"$empty" || fail "no-traffic hit rate should be null"
grep -qx memory_ratio=null <<<"$empty" || fail "no maxmemory ratio should be null"
json="$(printf '%s' "$info" | cmo_stats_from_info | cmo_stats_json)"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["hit_rate"]==0.9 and d["get_p99_usec"]==12.031' "$json" || fail "bad json: $json"
echo "stats-test: ok"
