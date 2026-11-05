#!/usr/bin/env bash
# ACL denial audit log (plan item 34).
# Reads ACL LOG from the running node(s) and appends new entries as JSON lines
# to CMO_AUDIT_LOG (default deploy/generated/acl-audit.jsonl), ready for any
# log shipper or SIEM. Run it from cron or a systemd timer.
#
#   ./acl-audit.sh            collect from the standalone node
#   ./acl-audit.sh NODE...    collect from these containers
#   ./acl-audit.sh --reset    also run ACL LOG RESET after a successful read
# Passwords and client names are never written; only addr, user, reason,
# context, object, count and timestamps are kept.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# stdin: valkey-cli --json ACL LOG output. $1 node name, $2 seen-ids file.
CMO_AUDIT_PY=$(cat <<'PY'
import json, sys
node, seen_path = sys.argv[1], sys.argv[2]
try:
    seen = set(open(seen_path).read().split())
except FileNotFoundError:
    seen = set()
raw = sys.stdin.read().strip() or "[]"
entries = json.loads(raw)
new = []
for e in entries:
    if isinstance(e, list):  # RESP2 flat pairs
        e = dict(zip(e[::2], e[1::2]))
    eid = "%s:%s:%s:%s" % (node, e.get("entry-id"), e.get("timestamp-created"), e.get("timestamp-last-updated"))
    if eid in seen:
        continue
    addr = ""
    for part in str(e.get("client-info", "")).split():
        if part.startswith("addr="):
            addr = part[5:]
    new.append(eid)
    print(json.dumps({
        "node": node, "user": e.get("username"), "reason": e.get("reason"),
        "context": e.get("context"), "object": e.get("object"), "count": e.get("count"),
        "addr": addr, "first_ms": e.get("timestamp-created"), "last_ms": e.get("timestamp-last-updated"),
    }, sort_keys=True))
with open(seen_path, "a") as f:
    for eid in new:
        f.write(eid + "\n")
PY
)
cmo_audit_convert() {
    python3 -c "$CMO_AUDIT_PY" "$1" "$2"
}

if [[ "${CMO_AUDIT_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

reset=0; nodes=()
for a in "$@"; do
    case "$a" in --reset) reset=1 ;; -h|--help) sed -n 2,11p "$0"; exit 0 ;; *) nodes+=("$a") ;; esac
done
cmo_load_env
[[ ${#nodes[@]} -gt 0 ]] || nodes=("$(cmo_standalone_name)")
out="${CMO_AUDIT_LOG:-$(cmo_generated_dir)/acl-audit.jsonl}"
mkdir -p "$(dirname "$out")"
seen="${out}.seen"
total=0
for n in "${nodes[@]}"; do
    lines="$(cmo_admin "$n" --json ACL LOG 128 | cmo_audit_convert "$n" "$seen")"
    if [[ -n "$lines" ]]; then
        printf '%s\n' "$lines" >>"$out"
        total=$((total + $(wc -l <<<"$lines")))
    fi
    [[ $reset == 1 ]] && cmo_admin "$n" ACL LOG RESET >/dev/null
done
echo "acl-audit: $total new entr$([[ $total == 1 ]] && echo y || echo ies) -> $out"
