#!/usr/bin/env bash
# Fork a new, separate database from a backup (plan item 56).
#
#   ./fork-from-backup.sh NAME BACKUP.rdb [PORT]    create fork (port default 6390)
#   ./fork-from-backup.sh --remove NAME             delete the fork and its volume
#
# Verifies the backup (.sha256 and RDB magic), copies it into a fresh Docker
# volume <prefix>-fork-NAME, and starts the cache-me-outside image on
# 127.0.0.1:PORT only. The source database is never touched. The fork uses
# the image defaults; users and passwords come from that image, not the backup.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
source ./lib.sh
die() { echo "fork: $*" >&2; exit 1; }
: "${CMO_FORK_IMAGE:=cache-me-outside:local}"

fork_name() {
    [[ "$1" =~ ^[a-z0-9][a-z0-9-]{0,30}$ ]] || die "name must be lowercase letters, digits, dashes (max 31)"
    printf '%s-fork-%s\n' "$(cmo_standalone_name)" "$1"
}

if [[ "${1:-}" == --remove ]]; then
    n="$(fork_name "${2:-}")"
    docker rm -f "$n" >/dev/null 2>&1 || true
    docker volume rm "$n" >/dev/null
    echo "removed $n"; exit 0
fi

name="${1:-}"; rdb="${2:-}"; port="${3:-6390}"
[[ -n "$name" && -n "$rdb" ]] || { sed -n 2,10p "$0"; exit 1; }
n="$(fork_name "$name")"
[[ "$port" =~ ^[0-9]+$ ]] && (( port >= 1024 && port <= 65535 )) || die "port must be 1024-65535"
[[ -f "$rdb" && -f "$rdb.sha256" ]] || die "missing $rdb or its .sha256"
[[ "$(awk '{print $1}' "$rdb.sha256")" == "$(sha256sum "$rdb" | awk '{print $1}')" ]] || die "checksum mismatch"
[[ "$(head -c 5 "$rdb")" == REDIS ]] || die "$rdb is not an RDB file"
docker inspect "$n" >/dev/null 2>&1 && die "$n already exists (use --remove first)"

docker volume create "$n" >/dev/null
# Copy the RDB in with a throwaway container; the backup dir is mounted read-only.
docker run --rm -v "$n:/data" -v "$(cd "$(dirname "$rdb")" && pwd):/src:ro" \
    --entrypoint sh "$CMO_FORK_IMAGE" -c "cp /src/$(basename "$rdb") /data/dump.rdb"
docker run -d --name "$n" --label cmo.fork-of="$(cmo_standalone_name)" \
    -p "127.0.0.1:$port:6379" -v "$n:/data" "$CMO_FORK_IMAGE" >/dev/null
echo "fork $n running on 127.0.0.1:$port from $(basename "$rdb")"
