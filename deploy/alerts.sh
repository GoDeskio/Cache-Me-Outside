#!/usr/bin/env bash
# Alert rules over stats.sh numbers (plan item 52). Run from cron or a timer.
#
#   ./alerts.sh            print firing alerts; exit 2 when any fire
#
# Thresholds (deploy/.env): CMO_ALERT_MEMORY_RATIO (default 0.90),
# CMO_ALERT_HIT_RATE_MIN (default 0.80, ignored with no traffic),
# CMO_ALERT_EVICTIONS_MAX (default 0), CMO_ALERT_GET_P99_USEC (default 5000).
# CMO_ALERT_WEBHOOK, when set to an https URL, receives one JSON POST per run
# with firing alerts (works with Slack-compatible incoming webhooks).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib.sh
source ./lib.sh
# shellcheck disable=SC2034
CMO_STATS_LIB=1
# shellcheck source=stats.sh
source ./stats.sh
unset CMO_STATS_LIB

# key=value stats on stdin -> one "severity rule message" line per alert.
cmo_alerts_eval() {
    awk -F= -v mem="${CMO_ALERT_MEMORY_RATIO:-0.90}" -v hit="${CMO_ALERT_HIT_RATE_MIN:-0.80}" \
        -v ev="${CMO_ALERT_EVICTIONS_MAX:-0}" -v p99="${CMO_ALERT_GET_P99_USEC:-5000}" '
        { v[$1]=$2 }
        END {
            if (v["memory_ratio"] != "null" && v["memory_ratio"]+0 >= mem+0) printf "critical memory Memory at %d%% of maxmemory\n", v["memory_ratio"]*100
            if (v["hit_rate"] != "null" && v["hit_rate"]+0 < hit+0) printf "warning hit_rate Hit rate %.1f%% is below %.0f%%\n", v["hit_rate"]*100, hit*100
            if (v["evicted_keys"]+0 > ev+0) printf "warning evictions %d keys evicted since start\n", v["evicted_keys"]
            if (v["get_p99_usec"] != "null" && v["get_p99_usec"]+0 > p99+0) printf "warning latency GET p99 %s us exceeds %s us\n", v["get_p99_usec"], p99
        }'
}

# Alert lines on stdin -> JSON body with a Slack-friendly "text" field.
cmo_alerts_json() {
    python3 -c '
import json, sys
host = sys.argv[1]
rows = [l.rstrip("\n").split(" ", 2) for l in sys.stdin if l.strip()]
alerts = [{"severity": s, "rule": r, "message": m} for s, r, m in rows]
text = "\n".join("[%s] %s: %s" % (a["severity"], host, a["message"]) for a in alerts)
print(json.dumps({"source": "cache-me-outside", "node": host, "alerts": alerts, "text": text}))
' "$1"
}

if [[ "${CMO_ALERTS_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

cmo_load_env
container="$(cmo_standalone_name)"
firing="$(cmo_admin "$container" INFO everything | cmo_stats_from_info | cmo_alerts_eval)"
[[ -z "$firing" ]] && { echo "ok: no alerts"; exit 0; }
printf '%s\n' "$firing"
if [[ -n "${CMO_ALERT_WEBHOOK:-}" ]]; then
    case "$CMO_ALERT_WEBHOOK" in https://*) ;; *) echo "CMO_ALERT_WEBHOOK must be https://" >&2; exit 1 ;; esac
    printf '%s\n' "$firing" | cmo_alerts_json "$container" |
        curl -fsS --max-time 10 -H 'content-type: application/json' --data-binary @- "$CMO_ALERT_WEBHOOK" >/dev/null ||
        echo "webhook delivery failed" >&2
fi
exit 2
