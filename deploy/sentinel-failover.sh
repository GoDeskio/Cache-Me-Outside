#!/usr/bin/env bash
# Crash the Sentinel primary and confirm a replica is promoted and accepts writes.
#   ./sentinel-failover.sh           start the stack, then fail over
#   ./sentinel-failover.sh --no-up   use the stack that is already running
#   ./sentinel-failover.sh --i-know  allow the production project
#
# The default project is cmo-test. The production project is refused before
# any container is killed, unless --i-know is passed.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

no_up=0
for arg in "$@"; do
    case "$arg" in
        --no-up) no_up=1 ;;
        --i-know) ;;
        *)
            echo "Unknown argument: ${arg}" >&2
            exit 1
            ;;
    esac
done

cmo_prepare_test_identity "$@"

if [[ "$no_up" -eq 0 ]]; then
    ./up.sh sentinel
fi
cmo_load_env

primary="$(cmo_member_name primary)"
# shellcheck disable=SC1090
source "$(cmo_state_file)"

replicas=()
sentinels=()
for spec in "${nodes[@]}"; do
    # shellcheck disable=SC2086
    set -- $spec
    if [[ "$2" == "replica" ]]; then
        replicas+=("$1")
    fi
done
for i in $(seq 1 "$sentinel_count"); do
    sentinels+=("$(cmo_member_name "sentinel-${i}")")
done

fail() {
    echo "failover: $*" >&2
    docker logs --tail 40 "${sentinels[0]}" >&2 || true
    docker logs --tail 40 "$primary" >&2 || true
    exit 1
}

cmo_wait_healthy "$primary"
for name in "${replicas[@]}" "${sentinels[@]}"; do
    cmo_wait_healthy "$name"
done

synced=0
for _i in $(seq 1 60); do
    synced=1
    for name in "${replicas[@]}"; do
        info="$(cmo_admin "$name" INFO replication || true)"
        if ! grep -q 'master_link_status:up' <<< "$info"; then
            synced=0
        fi
    done
    if [[ "$synced" -eq 1 ]]; then
        break
    fi
    sleep 1
done
[[ "$synced" -eq 1 ]] || fail "a replica did not finish the initial sync"

# A Sentinel that just restarted has not learned the replica yet. Killing the
# primary in that window ends in "no good replica". Wait until every Sentinel
# lists every replica.
known=0
for _i in $(seq 1 90); do
    known=1
    for sentinel in "${sentinels[@]}"; do
        listing="$(cmo_admin_port "$sentinel" "${CMO_SENTINEL_PORT}" SENTINEL REPLICAS "$CMO_SENTINEL_MASTER" 2>/dev/null || true)"
        for name in "${replicas[@]}"; do
            ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$name" 2>/dev/null || true)"
            if ! grep -Fq "$name" <<< "$listing" && { [[ -z "$ip" ]] || ! grep -Fq "$ip" <<< "$listing"; }; then
                known=0
            fi
        done
    done
    if [[ "$known" -eq 1 ]]; then
        break
    fi
    sleep 1
done
[[ "$known" -eq 1 ]] || fail "a sentinel does not list every replica yet"

cmo_app "$primary" SET cmo:failover before >/dev/null
old_ip="$(docker inspect --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$primary")"
[[ -n "$old_ip" ]] || fail "could not read the primary address"

# unless-stopped would bring the primary back and race the election.
docker update --restart=no "$primary" >/dev/null
docker kill "$primary" >/dev/null

new_addr=""
for _i in $(seq 1 90); do
    addr="$(cmo_admin_port "${sentinels[0]}" "${CMO_SENTINEL_PORT}" SENTINEL GET-PRIMARY-ADDR-BY-NAME "$CMO_SENTINEL_MASTER" 2>/dev/null || true)"
    new_addr="$(printf '%s\n' "$addr" | head -n 1 | tr -d '\r')"
    if [[ -n "$new_addr" && "$new_addr" != "$old_ip" && "$new_addr" != "$primary" ]]; then
        break
    fi
    new_addr=""
    sleep 1
done
[[ -n "$new_addr" ]] || fail "sentinel did not publish a new primary"

promoted=""
for candidate in "${replicas[@]}"; do
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

running="$(docker inspect --format '{{.State.Running}}' "$primary")"
[[ "$running" == "false" ]] || fail "old primary is still running"

discover="$(docker exec "${sentinels[0]}" valkey-cli -h 127.0.0.1 -p "${CMO_SENTINEL_PORT}" --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning SENTINEL GET-PRIMARY-ADDR-BY-NAME "$CMO_SENTINEL_MASTER" 2>&1 || true)"
case "$discover" in
    *NOPERM* | *ERR*) fail "app user cannot discover the primary: ${discover}" ;;
esac
[[ -n "$discover" ]] || fail "app user discovery returned nothing"

denied="$(docker exec "${sentinels[0]}" valkey-cli -h 127.0.0.1 -p "${CMO_SENTINEL_PORT}" --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning SENTINEL FAILOVER "$CMO_SENTINEL_MASTER" 2>&1 || true)"
case "$denied" in
    *NOPERM*) ;;
    *) fail "app user was allowed to run SENTINEL FAILOVER: ${denied}" ;;
esac

echo "failover: ok (sentinel promoted ${promoted}, writes resumed, old primary is down)"
