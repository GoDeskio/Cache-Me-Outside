#!/usr/bin/env bash
# Offline test for backup-export.sh with a fake `aws` on PATH.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
mkdir -p "$tmp/bin" "$tmp/b"
cat >"$tmp/bin/aws" <<'A'
#!/usr/bin/env bash
echo "$*" >>"$AWS_LOG"
if [[ "$*" == *head-object* ]]; then echo "${FAKE_SIZE:-9}"; fi
A
chmod +x "$tmp/bin/aws"
export PATH="$tmp/bin:$PATH" AWS_LOG="$tmp/log"
printf 'REDIS0011' >"$tmp/b/cmo-1.rdb"; (cd "$tmp/b" && sha256sum cmo-1.rdb >cmo-1.rdb.sha256)
s="$here/backup-export.sh"
"$s" "$tmp/b/cmo-1.rdb" s3://My_Bucket/x 2>/dev/null && fail bad-bucket
CMO_BACKUP_DIR="$tmp/b" "$s" --latest s3://acme-backups/cmo >/dev/null || fail export
grep -q "s3 cp --only-show-errors $tmp/b/cmo-1.rdb s3://acme-backups/cmo/cmo-1.rdb" "$tmp/log" || fail cp
grep -q -- "--bucket acme-backups --key cmo/cmo-1.rdb" "$tmp/log" || fail head
CMO_EXPORT_ENDPOINT=http://r2 "$s" "$tmp/b/cmo-1.rdb" s3://acme-backups 2>/dev/null && fail http-endpoint
: >"$tmp/log"; CMO_EXPORT_ENDPOINT=https://acct.r2.cloudflarestorage.com "$s" "$tmp/b/cmo-1.rdb" s3://acme-backups >/dev/null
grep -q -- "--endpoint-url https://acct.r2" "$tmp/log" || fail endpoint
FAKE_SIZE=3 "$s" "$tmp/b/cmo-1.rdb" s3://acme-backups 2>/dev/null && fail size-check
printf 'X' >>"$tmp/b/cmo-1.rdb"; : >"$tmp/log"
"$s" "$tmp/b/cmo-1.rdb" s3://acme-backups 2>/dev/null && fail damaged
[[ ! -s "$tmp/log" ]] || fail uploaded-damaged
echo "backup-export tests passed"
