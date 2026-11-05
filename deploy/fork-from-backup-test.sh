#!/usr/bin/env bash
# Offline test for fork-from-backup.sh with a fake docker.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
mkdir -p "$tmp/bin" "$tmp/b"
cat >"$tmp/bin/docker" <<'D'
#!/usr/bin/env bash
echo "$*" >>"$DOCKER_LOG"
[[ "$1" == inspect ]] && exit "${FAKE_EXISTS:-1}"
exit 0
D
chmod +x "$tmp/bin/docker"
export PATH="$tmp/bin:$PATH" DOCKER_LOG="$tmp/log" CMO_NAME_PREFIX=cmo-test
printf 'REDIS0011x' >"$tmp/b/a.rdb"; (cd "$tmp/b" && sha256sum a.rdb >a.rdb.sha256)
s="$here/fork-from-backup.sh"
"$s" Bad_Name "$tmp/b/a.rdb" 2>/dev/null && fail bad-name
"$s" qa "$tmp/b/a.rdb" 80 2>/dev/null && fail low-port
"$s" qa "$tmp/b/a.rdb" 6391 >/dev/null || fail create
grep -q "volume create cmo-test-fork-qa" "$tmp/log" || fail volume
grep -q -- "-p 127.0.0.1:6391:6379" "$tmp/log" || fail loopback
grep -q ":/src:ro" "$tmp/log" || fail readonly
FAKE_EXISTS=0 "$s" qa "$tmp/b/a.rdb" 2>/dev/null && fail exists
printf 'NOTRDBxxxx' >"$tmp/b/c.rdb"; (cd "$tmp/b" && sha256sum c.rdb >c.rdb.sha256)
"$s" qb "$tmp/b/c.rdb" 2>/dev/null && fail magic
printf 'X' >>"$tmp/b/a.rdb"; "$s" qc "$tmp/b/a.rdb" 2>/dev/null && fail checksum
: >"$tmp/log"; "$s" --remove qa >/dev/null; grep -q "volume rm cmo-test-fork-qa" "$tmp/log" || fail remove
echo "fork-from-backup tests passed"
