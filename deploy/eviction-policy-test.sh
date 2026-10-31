#!/usr/bin/env bash
# Offline test for eviction-policy.sh: no container needed.
set -euo pipefail
cd "$(dirname "$0")"
fail() { echo "FAIL: $*" >&2; exit 1; }
export CMO_POLICY_LIB=1
# shellcheck source=eviction-policy.sh
source ./eviction-policy.sh
for p in allkeys-lru allkeys-lfu volatile-ttl noeviction; do cmo_policy_valid "$p" || fail "$p should be valid"; done
for p in lru "" "allkeys-lru; FLUSHALL" ALLKEYS-LRU; do ! cmo_policy_valid "$p" || fail "'$p' should be rejected"; done
for p in "${CMO_POLICIES[@]}"; do [[ -n "$(cmo_policy_advice "$p")" ]] || fail "no advice for $p"; done
# Every picker choice must also be accepted by the entrypoint at boot.
for p in "${CMO_POLICIES[@]}"; do grep -q -- "$p" docker-entrypoint.sh || fail "entrypoint does not accept $p"; done
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
printf 'A=1\nCMO_MAXMEMORY_POLICY=allkeys-lru\n' > "$tmp"
cmo_env_set "$tmp" CMO_MAXMEMORY_POLICY allkeys-lfu
grep -qx CMO_MAXMEMORY_POLICY=allkeys-lfu "$tmp" || fail "env not rewritten"
[[ "$(grep -c CMO_MAXMEMORY_POLICY "$tmp")" == 1 ]] || fail "duplicate key"
printf 'A=1\n' > "$tmp"; cmo_env_set "$tmp" CMO_MAXMEMORY_POLICY noeviction
grep -qx CMO_MAXMEMORY_POLICY=noeviction "$tmp" || fail "env not appended"
[[ "$(bash ./eviction-policy.sh --list | wc -l)" == 8 ]] || fail "--list should print 8 policies"
echo "eviction-policy-test: ok"
