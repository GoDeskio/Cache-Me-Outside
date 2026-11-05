#!/usr/bin/env bash
# Offline test for ip-allowlist.sh: no Docker, no root, no iptables.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export CMO_ENV_FILE="$tmp/t.env"
printf 'CMO_HOST_PORT=7000\n' >"$CMO_ENV_FILE"
fail() { echo "FAIL: $*"; exit 1; }
s="$here/ip-allowlist.sh"
"$s" show | grep -q "not restricted" || fail show-empty
"$s" set 10.0.0.0/8 203.0.113.7 >/dev/null || fail set
grep -q '^CMO_ALLOWED_CIDRS=10.0.0.0/8,203.0.113.7/32$' "$CMO_ENV_FILE" || fail saved
for bad in 0.0.0.0/0 300.1.1.1 1.2.3.4/33 abc; do "$s" set "$bad" 2>/dev/null && fail "accepted $bad"; done
grep -q '^CMO_ALLOWED_CIDRS=10.0.0.0/8,203.0.113.7/32$' "$CMO_ENV_FILE" || fail kept-after-bad
r="$("$s" rules)"
grep -q -- "--dport 7000 -j CMO-ALLOW" <<<"$r" || fail port
grep -q -- "-s 203.0.113.7/32 -j RETURN" <<<"$r" || fail allow
[[ "$(tail -1 <<<"$r")" == "iptables -A CMO-ALLOW -j DROP" ]] || fail drop-last
if [[ $EUID -ne 0 ]]; then "$s" apply 2>/dev/null && fail apply-nonroot; fi
"$s" clear >/dev/null; "$s" rules 2>/dev/null && fail rules-after-clear
echo "ip-allowlist tests passed"
