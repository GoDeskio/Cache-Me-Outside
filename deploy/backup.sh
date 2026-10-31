#!/usr/bin/env bash
# Off-volume RDB backups with retention (plan items 3 and 54).
#
# Streams an RDB snapshot out of the running container with
# `valkey-cli --rdb -` (admin user) into CMO_BACKUP_DIR, which must be outside
# the Docker volume tree, writes a .sha256 next to it, then prunes old files.
#
#   CMO_BACKUP_DIR=/mnt/backups/cmo ./backup.sh          take one + prune
#   CMO_BACKUP_DIR=... ./backup.sh --prune-only           prune only
#   CMO_BACKUP_DIR=... ./backup.sh --verify FILE          check checksum + magic
#
# Retention: keep at least CMO_BACKUP_KEEP newest files (default 7) and drop
# anything older than CMO_BACKUP_MAX_AGE_DAYS (default 30). The newest backup
# is never deleted. Run it from cron or a systemd timer for daily backups.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck source=lib.sh
source ./lib.sh

: "${CMO_BACKUP_KEEP:=7}"
: "${CMO_BACKUP_MAX_AGE_DAYS:=30}"

die() { echo "backup: $*" >&2; exit 1; }

[[ "$CMO_BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || die "CMO_BACKUP_KEEP must be a positive integer"
[[ "$CMO_BACKUP_MAX_AGE_DAYS" =~ ^[0-9]+$ ]] || die "CMO_BACKUP_MAX_AGE_DAYS must be an integer"
[[ -n "${CMO_BACKUP_DIR:-}" ]] || die "set CMO_BACKUP_DIR to a directory outside the data volume"
case "$CMO_BACKUP_DIR" in
    /*) ;;
    *) die "CMO_BACKUP_DIR must be an absolute path" ;;
esac
case "$CMO_BACKUP_DIR" in
    /var/lib/docker* | /var/lib/containerd*) die "CMO_BACKUP_DIR must be off the Docker volume tree" ;;
esac

verify() {
    local file="$1"
    [[ -s "$file" ]] || die "missing or empty: ${file}"
    [[ -f "${file}.sha256" ]] || die "no checksum for ${file}"
    (cd "$(dirname "$file")" && sha256sum -c --status "$(basename "$file").sha256") \
        || die "checksum mismatch: ${file}"
    local magic
    magic="$(head -c 5 "$file")"
    [[ "$magic" == "REDIS" || "$magic" == "VALKE" ]] || die "not an RDB file: ${file}"
    echo "ok ${file}"
}

prune() {
    local files=() f i=0 now age_s
    now="$(date +%s)"
    age_s=$((CMO_BACKUP_MAX_AGE_DAYS * 86400))
    # Names sort by UTC timestamp, newest first.
    mapfile -t files < <(find "$CMO_BACKUP_DIR" -maxdepth 1 -type f -name 'cmo-*.rdb' -printf '%f\n' | sort -r)
    for f in "${files[@]}"; do
        i=$((i + 1))
        if ((i <= CMO_BACKUP_KEEP)); then continue; fi
        local mtime
        mtime="$(stat -c %Y "${CMO_BACKUP_DIR}/${f}")"
        if ((now - mtime > age_s)); then
            rm -f -- "${CMO_BACKUP_DIR}/${f}" "${CMO_BACKUP_DIR}/${f}.sha256"
            echo "pruned ${f}"
        fi
    done
}

mode="${1:-backup}"
case "$mode" in
    --verify) [[ $# -eq 2 ]] || die "usage: --verify FILE"; verify "$2"; exit 0 ;;
    --prune-only) prune; exit 0 ;;
    backup) ;;
    *) die "unknown argument: ${mode}" ;;
esac

umask 077
mkdir -p "$CMO_BACKUP_DIR"
cmo_load_env
container="$(cmo_standalone_name)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="${CMO_BACKUP_DIR}/cmo-${container}-${stamp}.rdb"
tmp="${out}.partial"
trap 'rm -f -- "$tmp"' EXIT

cmo_admin "$container" --rdb - >"$tmp" 2>/dev/null || die "RDB transfer failed"
[[ -s "$tmp" ]] || die "RDB transfer was empty"
mv -- "$tmp" "$out"
(cd "$CMO_BACKUP_DIR" && sha256sum "$(basename "$out")" >"$(basename "$out").sha256")
verify "$out"
prune
