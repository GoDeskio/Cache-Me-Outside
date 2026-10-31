#!/usr/bin/env bash
# Offline test for backup.sh: a stub `docker` streams a fake RDB, so no
# container or real data is touched.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/bin" "$work/out"
cat >"$work/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf 'REDIS0011fake-rdb-body'
STUB
chmod +x "$work/bin/docker"
printf 'CMO_ADMIN_USER=admin\nCMO_ADMIN_PASSWORD=test-only-password-123\n' >"$work/env"
export PATH="$work/bin:$PATH" CMO_ENV_FILE="$work/env" CMO_BACKUP_DIR="$work/out"
fail() { echo "FAIL: $*" >&2; exit 1; }

# Ten old backups, 40 days old.
for n in 01 02 03 04 05 06 07 08 09 10; do
    f="$work/out/cmo-cache-me-outside-202601${n}T000000Z.rdb"
    printf 'REDIS0011old' >"$f"
    (cd "$work/out" && sha256sum "$(basename "$f")" >"$(basename "$f").sha256")
    touch -d '40 days ago' "$f"
done

CMO_BACKUP_KEEP=3 ./backup.sh >/dev/null
count="$(find "$work/out" -name 'cmo-*.rdb' | wc -l)"
[[ "$count" -eq 3 ]] || fail "expected 3 backups after prune, got ${count}"
newest="$(find "$work/out" -name 'cmo-*.rdb' | sort -r | head -1)"
./backup.sh --verify "$newest" >/dev/null || fail "fresh backup did not verify"

# Young files are kept even past KEEP.
for n in 11 12; do touch "$work/out/cmo-cache-me-outside-202601${n}T000000Z.rdb"; done
CMO_BACKUP_KEEP=1 ./backup.sh --prune-only >/dev/null
[[ -f "$work/out/cmo-cache-me-outside-20260111T000000Z.rdb" ]] || fail "young backup was pruned"

# Tampering is caught.
printf 'x' >>"$newest"
if ./backup.sh --verify "$newest" 2>/dev/null; then fail "tampered backup verified"; fi

# Refusals.
if CMO_BACKUP_DIR=/var/lib/docker/volumes/x ./backup.sh 2>/dev/null; then fail "accepted docker volume path"; fi
if CMO_BACKUP_DIR=rel ./backup.sh 2>/dev/null; then fail "accepted relative path"; fi
if CMO_BACKUP_KEEP=0 ./backup.sh 2>/dev/null; then fail "accepted KEEP=0"; fi
echo "backup-test: ok"
