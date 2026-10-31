#!/usr/bin/env bash
# Offline test for alerts.sh rules: no container needed.
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAIL: $*" >&2; exit 1; }
export CMO_ALERTS_LIB=1
# shellcheck source=alerts.sh
source ./alerts.sh
hot=$'hit_rate=0.5000\nmemory_ratio=0.9500\nevicted_keys=12\nget_p99_usec=9000\n'
out="$(printf '%s' "$hot" | cmo_alerts_eval)"
for rule in memory hit_rate evictions latency; do grep -q " ${rule} " <<<"$out" || fail "rule ${rule} should fire: $out"; done
grep -q '^critical memory Memory at 95%' <<<"$out" || fail "memory message: $out"
calm=$'hit_rate=null\nmemory_ratio=null\nevicted_keys=0\nget_p99_usec=null\n'
[[ -z "$(printf '%s' "$calm" | cmo_alerts_eval)" ]] || fail "idle node should not alert"
[[ -z "$(printf '%s' "$hot" | CMO_ALERT_MEMORY_RATIO=0.99 CMO_ALERT_HIT_RATE_MIN=0.1 CMO_ALERT_EVICTIONS_MAX=100 CMO_ALERT_GET_P99_USEC=10000 cmo_alerts_eval)" ]] || fail "thresholds ignored"
json="$(printf '%s' "$out" | cmo_alerts_json node-a)"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert len(d["alerts"])==4 and d["node"]=="node-a" and "[critical] node-a" in d["text"]' "$json" || fail "bad json: $json"
echo "alerts-test: ok"
