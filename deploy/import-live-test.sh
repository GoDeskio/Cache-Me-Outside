#!/usr/bin/env bash
# Offline test for import-live.sh with a fake cmo_admin: no Docker.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
CMO_IMPORT_LIB=1 source "$here/import-live.sh"
fail() { echo "FAIL: $*"; exit 1; }
CALLS=(); ROLE=master; LINK=down; SYNC=1
cmo_admin() {
    shift; CALLS+=("$*")
    case "$1 ${2:-}" in
        "INFO replication") printf 'role:%s\r\nmaster_host:old\r\nmaster_port:6379\r\nmaster_link_status:%s\r\nmaster_sync_in_progress:%s\r\nmaster_last_io_seconds_ago:0\r\n' "$ROLE" "$LINK" "$SYNC" ;;
        "DBSIZE ") echo 42 ;;
        *) echo OK ;;
    esac
}
cmo_import_valid_target 'bad host;' 6379 2>/dev/null && fail host
cmo_import_valid_target h 70000 2>/dev/null && fail port
CMO_IMPORT_USER=repl CMO_IMPORT_PASSWORD=s3cret cmo_import_start n1 old.example 6379 >/dev/null
[[ "${CALLS[*]}" == *"CONFIG SET masteruser repl"* && "${CALLS[*]}" == *"REPLICAOF old.example 6379"* ]] || fail start
ROLE=slave
set +e; out="$(cmo_import_status n1)"; rc=$?; set -e
[[ $rc == 3 && "$out" == syncing* ]] || fail syncing
LINK=up; SYNC=0
[[ "$(cmo_import_status n1)" == "in sync with old:6379, keys=42"* ]] || fail insync
ROLE=master; CALLS=()
cmo_import_stop n1
[[ "${CALLS[0]}" == "REPLICAOF NO ONE" && "${CALLS[1]}" == "CONFIG SET masterauth " ]] || fail stop
ROLE=slave; cmo_import_start n1 h 1 2>/dev/null && fail replica-target
echo "import-live tests passed"
