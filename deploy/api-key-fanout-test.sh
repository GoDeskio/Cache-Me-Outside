#!/usr/bin/env bash
# Offline test: api-key.sh writes records and ACL users on every data node of
# a Sentinel/cluster project, skips sentinels, and fails loudly on a bad node.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
mkdir -p "$work/bin"
deploy="$(pwd)"
cat >"$work/bin/docker" <<STUB
#!/usr/bin/env bash
if [[ "\$1" == ps ]]; then printf 'cmo-t-data-0\ncmo-t-data-1\ncmo-t-sentinel-0\n'; exit 0; fi
shift # exec
while [[ "\$1" == -* ]]; do [[ "\$1" == -u ]] && shift; shift; done
c="\$1"; shift
[[ -e "$work/broken-\$c" ]] && exit 1
mkdir -p "$work/data-\$c"
case "\$1" in
    printenv) [[ "\$c" == *sentinel* ]] && echo sentinel || echo primary ;;
    sh) exec sh -c "\${3//\/data/$work/data-\$c}" ;;
    docker-entrypoint.sh) CMO_DATA_DIR="$work/data-\$c" exec "$deploy/docker-entrypoint.sh" --render-keys ;;
    valkey-cli) printf '%s %s\n' "\$c" "\$*" >>"$work/cli.log"; echo OK ;;
esac
STUB
chmod +x "$work/bin/docker"
printf 'CMO_ADMIN_USER=admin\nCMO_ADMIN_PASSWORD=test-only-password-123\nCMO_PROJECT=cmo-t\nCMO_TOPOLOGY=sentinel\n' >"$work/env"
export PATH="$work/bin:$PATH" CMO_ENV_FILE="$work/env" CMO_TOPOLOGY=sentinel CMO_PROJECT=cmo-t
fail() { echo "FAIL: $*" >&2; exit 1; }

out="$(./api-key.sh create --scope rw --prefix app:)"
id="$(sed -n 's/^user: //p' <<<"$out")"
[[ "$id" =~ ^key-[0-9a-f]{12}$ ]] || fail "no id: $out"
for n in 0 1; do
    grep -q "^$id " "$work/data-cmo-t-data-$n/cmo-keys" || fail "record missing on data-$n"
    grep -q "^cmo-t-data-$n .*ACL SETUSER $id " "$work/cli.log" || fail "user not applied on data-$n"
done
[[ ! -e "$work/data-cmo-t-sentinel-0/cmo-keys" ]] || fail "sentinel got records"
grep -q "^cmo-t-sentinel-0 .*ACL" "$work/cli.log" && fail "sentinel got ACL commands"
secret="$(sed -n 's/^password: //p' <<<"$out")"
grep -rq -- "$secret" "$work"/data-* && fail "plaintext secret stored"

./api-key.sh revoke "$id" >/dev/null
for n in 0 1; do
    grep -q "^$id " "$work/data-cmo-t-data-$n/cmo-keys" && fail "record left on data-$n"
    grep -q "^cmo-t-data-$n .*ACL DELUSER $id" "$work/cli.log" || fail "user not deleted on data-$n"
done

touch "$work/broken-cmo-t-data-1"
if ./api-key.sh create --scope ro >"$work/o" 2>"$work/e"; then fail "partial failure exited 0"; fi
grep -q "rerun" "$work/e" || fail "no rerun hint: $(cat "$work/e")"
rm "$work/broken-cmo-t-data-1"

CMO_KEYS_CONTAINERS="cmo-t-data-1" ./api-key.sh create --scope ro >/dev/null
[[ "$(wc -l <"$work/data-cmo-t-data-1/cmo-keys")" -ge 1 ]] || fail "override ignored"
rm -rf "$work/data-cmo-t-data-0"; mkdir -p "$work/data-cmo-t-data-0"
CMO_KEYS_CONTAINERS="cmo-t-data-1 cmo-t-data-0" ./api-key.sh sync >/dev/null
cmp -s "$work/data-cmo-t-data-1/cmo-keys" "$work/data-cmo-t-data-0/cmo-keys" || fail "sync did not copy"
echo "api-key-fanout-test: ok"
