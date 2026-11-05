#!/usr/bin/env bash
# Offline test for acl-audit.sh conversion: no Docker.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
CMO_AUDIT_LIB=1 source "$here/acl-audit.sh"
fail() { echo "FAIL: $*"; exit 1; }
log='[{"count":2,"reason":"command","context":"toplevel","object":"flushall","username":"app","age-seconds":1.2,"client-info":"id=7 addr=10.0.0.5:5000 laddr=x name=secretname","entry-id":0,"timestamp-created":1000,"timestamp-last-updated":1500},
["count",1,"reason","auth","context","toplevel","object","AUTH","username","bob","client-info","id=8 addr=10.0.0.6:1","entry-id",1,"timestamp-created",2000,"timestamp-last-updated",2000]]'
out="$(cmo_audit_convert n1 "$tmp/seen" <<<"$log")"
[[ $(wc -l <<<"$out") == 2 ]] || fail count
grep -q '"addr": "10.0.0.5:5000"' <<<"$out" || fail addr
grep -q '"reason": "auth"' <<<"$out" || fail resp2
grep -q secretname <<<"$out" && fail leaked-name
[[ -z "$(cmo_audit_convert n1 "$tmp/seen" <<<"$log")" ]] || fail dedupe
log2="${log/\"timestamp-last-updated\":1500/\"timestamp-last-updated\":1600}"
[[ $(cmo_audit_convert n1 "$tmp/seen" <<<"$log2" | wc -l) == 1 ]] || fail updated-entry
[[ -z "$(cmo_audit_convert n1 "$tmp/seen" <<<"")" ]] || fail empty
echo "acl-audit tests passed"
