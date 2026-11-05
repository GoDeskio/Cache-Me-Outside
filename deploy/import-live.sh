#!/usr/bin/env bash
# Live import from another Redis/Valkey server (plan item 57).
# The Cache Me Outside node replicates from the source until you cut over.
#
#   ./import-live.sh start HOST PORT [NODE]   begin syncing (source auth from
#                                             CMO_IMPORT_USER / CMO_IMPORT_PASSWORD)
#   ./import-live.sh status [NODE]           link state, sync progress, key count
#   ./import-live.sh cutover [NODE]          stop replicating; node becomes writable
#   ./import-live.sh abort [NODE]            same as cutover but says so in the log
# WARNING: start replaces all data on NODE with the source's data.
# Source must allow replication from this host (REPLICAOF/PSYNC, and the
# source ACL user needs +psync +replconf +ping). Standalone nodes only.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

cmo_import_field() { tr -d '\r' | sed -n "s/^$1://p" | head -1; }

cmo_import_valid_target() {
    local host="$1" port="$2"
    [[ "$host" =~ ^[A-Za-z0-9.-]{1,253}$ ]] || { echo "bad host" >&2; return 1; }
    [[ "$port" =~ ^[0-9]{1,5}$ ]] && (( port >= 1 && port <= 65535 )) || { echo "bad port" >&2; return 1; }
}

cmo_import_start() {
    local node="$1" host="$2" port="$3" role
    cmo_import_valid_target "$host" "$port"
    role="$(cmo_admin "$node" INFO replication | cmo_import_field role)"
    [[ "$role" == master ]] || { echo "$node is a $role; import into a standalone primary only" >&2; return 1; }
    if [[ -n "${CMO_IMPORT_USER:-}" ]]; then cmo_admin "$node" CONFIG SET masteruser "$CMO_IMPORT_USER" >/dev/null; fi
    if [[ -n "${CMO_IMPORT_PASSWORD:-}" ]]; then cmo_admin "$node" CONFIG SET masterauth "$CMO_IMPORT_PASSWORD" >/dev/null; fi
    cmo_admin "$node" REPLICAOF "$host" "$port" >/dev/null
    echo "import started: $node <- $host:$port (check with: $0 status)"
}

cmo_import_status() {
    local node="$1" info keys
    info="$(cmo_admin "$node" INFO replication)"
    keys="$(cmo_admin "$node" DBSIZE | tr -d '\r')"
    local role link sync
    role="$(cmo_import_field role <<<"$info")"
    link="$(cmo_import_field master_link_status <<<"$info")"
    sync="$(cmo_import_field master_sync_in_progress <<<"$info")"
    if [[ "$role" != slave ]]; then
        echo "not importing (role=$role, keys=$keys)"; return 0
    fi
    if [[ "$link" == up && "$sync" == 0 ]]; then
        echo "in sync with $(cmo_import_field master_host <<<"$info"):$(cmo_import_field master_port <<<"$info"), keys=$keys, lag=$(cmo_import_field master_last_io_seconds_ago <<<"$info")s. Ready to cut over."
    else
        echo "syncing (link=${link:-?}, initial_sync=${sync:-?}, keys=$keys)"
        return 3
    fi
}

cmo_import_stop() {
    local node="$1"
    cmo_admin "$node" REPLICAOF NO ONE >/dev/null
    cmo_admin "$node" CONFIG SET masterauth "" >/dev/null
    cmo_admin "$node" CONFIG SET masteruser "" >/dev/null
}

if [[ "${CMO_IMPORT_LIB:-}" == 1 ]]; then return 0 2>/dev/null || exit 0; fi

cmd="${1:-}"; shift || true
cmo_load_env
case "$cmd" in
    start) [[ $# -ge 2 ]] || { sed -n 2,13p "$0"; exit 1; }; cmo_import_start "${3:-$(cmo_standalone_name)}" "$1" "$2" ;;
    status) cmo_import_status "${1:-$(cmo_standalone_name)}" ;;
    cutover) cmo_import_stop "${1:-$(cmo_standalone_name)}"; echo "cut over: node is a writable primary now. Point apps at it." ;;
    abort) cmo_import_stop "${1:-$(cmo_standalone_name)}"; echo "import aborted; node kept whatever was copied so far" ;;
    *) sed -n 2,13p "$0"; exit 1 ;;
esac
