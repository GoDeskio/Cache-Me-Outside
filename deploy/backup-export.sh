#!/usr/bin/env bash
# Export a backup to the customer's own bucket (plan item 58).
#
#   ./backup-export.sh FILE.rdb s3://bucket/prefix/     (or latest: --latest)
# Uses the AWS CLI already installed on the host; credentials come from the
# customer's normal AWS profile/env (this script never reads or stores them).
# For Cloudflare R2 or other S3-compatible stores set CMO_EXPORT_ENDPOINT
# (https only). Verifies the .sha256 first, uploads the RDB and its checksum,
# then checks the uploaded size matches.
set -euo pipefail
die() { echo "backup-export: $*" >&2; exit 1; }

src="${1:-}"; dest="${2:-}"
[[ -n "$src" && -n "$dest" ]] || { sed -n 2,10p "$0"; exit 1; }
[[ "$dest" =~ ^s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9](/.*)?$ ]] || die "destination must be s3://bucket/prefix"
[[ "$dest" == */ ]] || dest="$dest/"
if [[ "$src" == --latest ]]; then
    [[ -n "${CMO_BACKUP_DIR:-}" ]] || die "--latest needs CMO_BACKUP_DIR"
    src="$(ls -1t "$CMO_BACKUP_DIR"/*.rdb 2>/dev/null | head -1)"
    [[ -n "$src" ]] || die "no backups in $CMO_BACKUP_DIR"
fi
[[ -f "$src" && -f "$src.sha256" ]] || die "missing $src or its .sha256"
command -v aws >/dev/null || die "install the AWS CLI on this host"
endpoint=()
if [[ -n "${CMO_EXPORT_ENDPOINT:-}" ]]; then
    [[ "$CMO_EXPORT_ENDPOINT" == https://* ]] || die "CMO_EXPORT_ENDPOINT must be https"
    endpoint=(--endpoint-url "$CMO_EXPORT_ENDPOINT")
fi

want="$(awk '{print $1}' "$src.sha256")"
have="$(sha256sum "$src" | awk '{print $1}')"
[[ "$want" == "$have" ]] || die "checksum mismatch for $src; not exporting a damaged backup"

name="$(basename "$src")"
aws "${endpoint[@]}" s3 cp --only-show-errors "$src" "$dest$name"
aws "${endpoint[@]}" s3 cp --only-show-errors "$src.sha256" "$dest$name.sha256"
size_local="$(stat -c %s "$src")"
size_remote="$(aws "${endpoint[@]}" s3api head-object --bucket "$(cut -d/ -f3 <<<"$dest")" --key "$(cut -d/ -f4- <<<"$dest")$name" --query ContentLength --output text)"
[[ "$size_remote" == "$size_local" ]] || die "uploaded size $size_remote != local $size_local"
echo "exported $name ($size_local bytes) to $dest"
