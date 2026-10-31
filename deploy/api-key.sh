#!/usr/bin/env bash
# Scoped, expiring API keys for the standalone node (plan item 63).
# Design: docs/cache-me-outside/api-keys-design.md
#
#   ./api-key.sh create --scope ro|rw [--prefix P] [--ttl-days N]
#   ./api-key.sh list
#   ./api-key.sh revoke key-<12hex>
#   ./api-key.sh sweep            remove expired keys (run from cron)
#
# Records go to /data/cmo-keys on the volume (hash only) and are applied live
# from the container's own renderer, so a restart produces the same users.
# The secret is printed once on create and is never stored.
set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
source ./lib.sh

die() { echo "api-key: $*" >&2; exit 1; }
cmo_load_env
container="${CMO_KEYS_CONTAINER:-$(cmo_standalone_name)}"
store=/data/cmo-keys

in_ct() { docker exec -i -u valkey "$container" sh -c "$1"; }
read_store() { in_ct "cat ${store} 2>/dev/null || true"; }
write_store() { in_ct "umask 077; cat > ${store}.new && mv ${store}.new ${store}"; }

# Apply rendered lines for the given ids (all when none) via ACL SETUSER.
apply() {
    local line
    while read -r line; do
        [[ -n "$line" ]] || continue
        # shellcheck disable=SC2086
        set -- $line
        shift # drop "user"
        cmo_admin "$container" ACL SETUSER "$@" >/dev/null
    done < <(docker exec -u valkey "$container" docker-entrypoint.sh --render-keys)
}

deluser() { cmo_admin "$container" ACL DELUSER "$1" >/dev/null; }

cmd="${1:-}"; shift || true
case "$cmd" in
    create)
        scope="" prefix="-" ttl=0
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --scope) scope="${2:-}"; shift 2 ;;
                --prefix) prefix="${2:-}"; shift 2 ;;
                --ttl-days) ttl="${2:-}"; shift 2 ;;
                *) die "unknown option: $1" ;;
            esac
        done
        [[ "$scope" == ro || "$scope" == rw ]] || die "--scope must be ro or rw"
        [[ "$prefix" == - || "$prefix" =~ ^[A-Za-z0-9:_.-]{1,64}$ ]] || die "bad --prefix"
        [[ "$ttl" =~ ^[0-9]+$ ]] || die "--ttl-days must be a whole number"
        id="key-$(openssl rand -hex 6)"
        secret="$(openssl rand -hex 24)"
        hash="$(printf '%s' "$secret" | sha256sum | cut -d' ' -f1)"
        exp=0
        ((ttl == 0)) || exp=$(($(date +%s) + ttl * 86400))
        { read_store; printf '%s %s %s %s %s\n' "$id" "$exp" "$scope" "$prefix" "$hash"; } | write_store
        apply
        printf 'user: %s\npassword: %s\n(shown once; store it now)\n' "$id" "$secret"
        ;;
    list)
        now="$(date +%s)"
        read_store | while read -r id exp scope prefix _; do
            [[ -n "$id" ]] || continue
            if [[ "$exp" == 0 ]]; then when=never
            elif ((exp <= now)); then when="expired"
            else when="$(date -u -d "@${exp}" +%Y-%m-%dT%H:%MZ)"; fi
            printf '%s\t%s\tprefix=%s\texpires=%s\n' "$id" "$scope" "$prefix" "$when"
        done
        ;;
    revoke)
        id="${1:-}"
        [[ "$id" =~ ^key-[0-9a-f]{12}$ ]] || die "usage: revoke key-<12hex>"
        read_store | awk -v id="$id" '$1 != id' | write_store
        deluser "$id"
        echo "revoked ${id}"
        ;;
    sweep)
        now="$(date +%s)"
        current="$(read_store)"
        expired="$(awk -v now="$now" '$2 != 0 && $2 <= now { print $1 }' <<<"$current")"
        awk -v now="$now" '!($2 != 0 && $2 <= now)' <<<"$current" | write_store
        for id in $expired; do deluser "$id"; echo "expired ${id}"; done
        ;;
    *) sed -n '2,10p' "$0"; exit 1 ;;
esac
