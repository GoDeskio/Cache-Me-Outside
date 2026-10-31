#!/usr/bin/env bash
# Offline test for API keys: the entrypoint renderer and api-key.sh, with a
# stub `docker` that maps /data to a temp dir and logs valkey-cli calls.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/bin" "$work/data"
deploy="$(pwd)"
cat >"$work/bin/docker" <<STUB
#!/usr/bin/env bash
# docker exec [-i] [-u valkey] CONTAINER CMD...
shift
while [[ "\$1" == -* ]]; do [[ "\$1" == -u ]] && shift; shift; done
shift
case "\$1" in
    sh) exec sh -c "\${3//\/data/$work/data}" ;;
    docker-entrypoint.sh) CMO_DATA_DIR="$work/data" exec "$deploy/docker-entrypoint.sh" --render-keys ;;
    valkey-cli) printf '%s\n' "\$*" >>"$work/cli.log"; echo OK ;;
esac
STUB
chmod +x "$work/bin/docker"
printf 'CMO_ADMIN_USER=admin\nCMO_ADMIN_PASSWORD=test-only-password-123\n' >"$work/env"
export PATH="$work/bin:$PATH" CMO_ENV_FILE="$work/env"
fail() { echo "FAIL: $*" >&2; exit 1; }
h="$(printf x | sha256sum | cut -d' ' -f1)"
render() { CMO_DATA_DIR="$work/data" ./docker-entrypoint.sh --render-keys 2>"$work/err"; }

# Renderer: valid, expired, malformed and injection attempts.
cat >"$work/data/cmo-keys" <<REC
key-0123456789ab 0 ro app: $h
key-aaaaaaaaaaaa 1 rw - $h
key-bbbbbbbbbbbb 0 admin - $h
key-cccccccccccc 0 rw x*+@all $h
admin 0 rw - $h
key-dddddddddddd 0 rw - $h +@all
REC
out="$(render)"
[[ "$(wc -l <<<"$out")" -eq 1 ]] || fail "expected one rendered line, got: $out"
[[ "$out" == "user key-0123456789ab on #$h resetchannels resetkeys ~app:* -@all +@read +ping +auth +hello -@dangerous -@admin" ]] || fail "bad line: $out"
[[ "$(grep -c malformed "$work/err")" -eq 4 ]] || fail "malformed records not all reported"

# api-key.sh lifecycle.
: >"$work/data/cmo-keys"
created="$(./api-key.sh create --scope rw --prefix sess: --ttl-days 1)"
id="$(sed -n 's/^user: //p' <<<"$created")"
secret="$(sed -n 's/^password: //p' <<<"$created")"
[[ "$id" =~ ^key-[0-9a-f]{12}$ ]] || fail "bad id: $id"
grep -q "$secret" "$work/data/cmo-keys" && fail "secret stored in plaintext"
grep -q "$(printf '%s' "$secret" | sha256sum | cut -d' ' -f1)" "$work/data/cmo-keys" || fail "hash not stored"
grep -q "ACL SETUSER ${id} on #" "$work/cli.log" || fail "key not applied live"
./api-key.sh list | grep -q "${id}	rw	prefix=sess:" || fail "list missing key"
./api-key.sh revoke "$id" >/dev/null
grep -q "$id" "$work/data/cmo-keys" && fail "revoke left the record"
grep -q "ACL DELUSER ${id}" "$work/cli.log" || fail "revoke did not delete user"

printf 'key-eeeeeeeeeeee 1 ro - %s\nkey-ffffffffffff 0 ro - %s\n' "$h" "$h" >"$work/data/cmo-keys"
./api-key.sh sweep | grep -q "expired key-eeeeeeeeeeee" || fail "sweep missed expired key"
grep -q key-eeeeeeeeeeee "$work/data/cmo-keys" && fail "expired record kept"
grep -q key-ffffffffffff "$work/data/cmo-keys" || fail "sweep removed a live key"
if ./api-key.sh create --scope admin 2>/dev/null; then fail "accepted admin scope"; fi
if ./api-key.sh create --scope ro --prefix 'a b' 2>/dev/null; then fail "accepted bad prefix"; fi
echo "api-key-test: ok"
