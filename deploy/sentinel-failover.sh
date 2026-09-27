#!/usr/bin/env bash
# Crash the Sentinel primary and confirm a replica is promoted and accepts writes.
#   ./sentinel-failover.sh           start the stack, then fail over
#   ./sentinel-failover.sh --no-up   use the stack that is already running
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

if [[ "${1:-}" != "--no-up" ]]; then
    ./up.sh sentinel
fi
cmo_load_env

fail() {
    echo "failover: $*" >&2
    docker logs --tail 40 cmo-sentinel-1 >&2 || true
    docker logs --tail 40 cmo-primary >&2 || true
    exit 1
}

cmo_wait_healthy cmo-primary
cmo_wait_healthy cmo-replica-1
cmo_wait_healthy cmo-sentinel-1

synced=0
for _i in $(seq 1 60); do
    info="$(cmo_admin cmo-replica-1 INFO replication || true)"
    if grep -q 'master_link_status:up' <<< "$info"; then
        synced=1
        break
    fi
    sleep 1
done
[[ "$synced" -eq 1 ]] || fail "replica did not finish the initial sync"

cmo_app cmo-primary SET cmo:failover before >/dev/null
old_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' cmo-primary)"
[[ -n "$old_ip" ]] || fail "could not read the primary address"

# unless-stopped would bring the primary back and race the election.
docker update --restart=no cmo-primary >/dev/null
docker kill cmo-primary >/dev/null

new_addr=""
for _i in $(seq 1 60); do
    addr="$(cmo_admin_port cmo-sentinel-1 "${CMO_SENTINEL_PORT}" SENTINEL GET-PRIMARY-ADDR-BY-NAME "$CMO_SENTINEL_MASTER" 2>/dev/null || true)"
    new_addr="$(printf '%s\n' "$addr" | head -n 1 | tr -d '\r')"
    if [[ -n "$new_addr" && "$new_addr" != "$old_ip" && "$new_addr" != "cmo-primary" ]]; then
        break
    fi
    new_addr=""
    sleep 1
done
[[ -n "$new_addr" ]] || fail "sentinel did not publish a new primary"

promoted=""
for candidate in cmo-replica-1 cmo-replica-2 cmo-replica-3; do
    if ! docker inspect "$candidate" >/dev/null 2>&1; then
        continue
    fi
    ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$candidate")"
    host="$(docker inspect --format '{{.Config.Hostname}}' "$candidate")"
    if [[ "$new_addr" == "$ip" || "$new_addr" == "$host" || "$new_addr" == "$candidate" ]]; then
        promoted="$candidate"
        break
    fi
done
[[ -n "$promoted" ]] || fail "new primary address ${new_addr} did not match a replica"

wrote=0
for _i in $(seq 1 30); do
    if cmo_app "$promoted" SET cmo:failover after >/dev/null 2>&1; then
        wrote=1
        break
    fi
    sleep 1
done
[[ "$wrote" -eq 1 ]] || fail "promoted node ${promoted} did not accept a write"
got="$(cmo_app "$promoted" GET cmo:failover | tr -d '\r')"
[[ "$got" == "after" ]] || fail "promoted node returned '${got}'"

running="$(docker inspect --format '{{.State.Running}}' cmo-primary)"
[[ "$running" == "false" ]] || fail "old primary is still running"

discover="$(docker exec cmo-sentinel-1 valkey-cli -h 127.0.0.1 -p "${CMO_SENTINEL_PORT}" --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning SENTINEL GET-PRIMARY-ADDR-BY-NAME "$CMO_SENTINEL_MASTER" 2>&1 || true)"
case "$discover" in
    *NOPERM* | *ERR*) fail "app user cannot discover the primary: ${discover}" ;;
esac
[[ -n "$discover" ]] || fail "app user discovery returned nothing"

denied="$(docker exec cmo-sentinel-1 valkey-cli -h 127.0.0.1 -p "${CMO_SENTINEL_PORT}" --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning SENTINEL FAILOVER "$CMO_SENTINEL_MASTER" 2>&1 || true)"
case "$denied" in
    *NOPERM*) ;;
    *) fail "app user was allowed to run SENTINEL FAILOVER: ${denied}" ;;
esac

echo "failover: ok (sentinel promoted ${promoted}, writes resumed, old primary is down)"
