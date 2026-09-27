#!/usr/bin/env bash
# Verify auth, the restricted app user, persistence, and the -cmo marker.
set -euo pipefail

cd "$(dirname "$0")"

generate_env=0
if [[ "${1:-}" == "--generate-env" ]]; then
    generate_env=1
    shift
fi

if [[ ! -f .env && "$generate_env" -eq 1 ]]; then
    umask 077
    admin_password="$(openssl rand -hex 24)"
    app_password="$(openssl rand -hex 24)"
    cat > .env <<EOF
CMO_ADMIN_USER=admin
CMO_ADMIN_PASSWORD=${admin_password}
CMO_APP_USER=app
CMO_APP_PASSWORD=${app_password}
CMO_BIND_ADDRESS=127.0.0.1
CMO_HOST_PORT=6379
CMO_PORT=6379
CMO_MAXMEMORY=256mb
CMO_MAXMEMORY_POLICY=allkeys-lru
CMO_CONTAINER_MEMORY=512m
EOF
    chmod 600 .env
    unset admin_password app_password
    echo "Wrote deploy/.env with generated passwords. The passwords were not printed."
fi

if [[ "${1:-}" != "--no-up" ]]; then
    ./up.sh
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

: "${CMO_ADMIN_USER:=admin}"
: "${CMO_APP_USER:=app}"
: "${CMO_PORT:=6379}"

fail() {
    echo "smoke: $*" >&2
    docker logs --tail 80 cache-me-outside >&2 || true
    exit 1
}

wait_healthy() {
    local _i status
    for _i in $(seq 1 60); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' cache-me-outside 2>/dev/null || true)"
        if [[ "$status" == "healthy" ]]; then
            return 0
        fi
        sleep 1
    done
    fail "container did not become healthy (last status: ${status:-missing})"
}

cli() {
    local user="$1"
    local pass="$2"
    shift 2
    docker exec cache-me-outside \
        valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
        --user "$user" -a "$pass" --no-auth-warning "$@"
}

expect_noper() {
    local command_name="$1"
    shift
    local out
    out="$(cli "$CMO_APP_USER" "$CMO_APP_PASSWORD" "$@" 2>&1 || true)"
    case "$out" in
        *NOPERM*) ;;
        *) fail "${command_name} was not denied for the app user: ${out}" ;;
    esac
}

wait_healthy

published="$(docker port cache-me-outside 6379/tcp)"
if [[ -z "$published" ]]; then
    fail "container port 6379 is not published"
fi
if printf '%s\n' "$published" | grep -Eq '^(0\.0\.0\.0|\[::\]|::):'; then
    fail "host port is published on all interfaces: ${published}"
fi

unauth="$(docker exec cache-me-outside valkey-cli -h 127.0.0.1 -p "$CMO_PORT" PING 2>&1 || true)"
case "$unauth" in
    *NOAUTH*) ;;
    *) fail "unauthenticated PING was not rejected: ${unauth}" ;;
esac

cli "$CMO_APP_USER" "$CMO_APP_PASSWORD" SET cmo:smoke persisted >/dev/null
got="$(cli "$CMO_APP_USER" "$CMO_APP_PASSWORD" GET cmo:smoke | tr -d '\r')"
[[ "$got" == "persisted" ]] || fail "GET returned '${got}'"
# appendfsync everysec: give the AOF a chance to hit disk before the snapshot.
sleep 2

expect_noper FLUSHALL FLUSHALL
expect_noper FLUSHDB FLUSHDB
expect_noper CONFIG CONFIG GET maxmemory
expect_noper KEYS KEYS '*'

# DEBUG is denied by ACL and also by enable-debug-command (default: no).
debug_out="$(cli "$CMO_APP_USER" "$CMO_APP_PASSWORD" DEBUG SLEEP 0 2>&1 || true)"
case "$debug_out" in
    *NOPERM* | *"DEBUG command not allowed"*) ;;
    *) fail "DEBUG was not denied for the app user: ${debug_out}" ;;
esac

protected="$(cli "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" CONFIG GET protected-mode 2>&1 || true)"
case "$protected" in
    *NOPERM*) fail "admin user cannot read config" ;;
    *yes*) ;;
    *) fail "protected-mode is not yes: ${protected}" ;;
esac

info="$(cli "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" INFO server)"
case "$info" in
    *"cmo_version:"*"-cmo"*) ;;
    *) fail "INFO server is missing the -cmo marker" ;;
esac
version="$(printf '%s\n' "$info" | awk -F: '/^valkey_version:/{gsub(/\r/, "", $2); print $2}')"
case "$version" in
    "" | *-* | *[!0-9.]*) fail "valkey_version is not a numeric major.minor.patch value: '${version}'" ;;
esac

# AOF everysec needs a moment, then an RDB snapshot should land on the volume.
sleep 2
cli "$CMO_ADMIN_USER" "$CMO_ADMIN_PASSWORD" BGSAVE >/dev/null || true
saved=0
for _i in $(seq 1 30); do
    if docker exec cache-me-outside sh -c 'test -s /data/dump.rdb && test -d /data/appendonlydir'; then
        saved=1
        break
    fi
    sleep 1
done
[[ "$saved" -eq 1 ]] || fail "RDB snapshot or AOF directory is missing on the data volume"

docker compose restart cache-me-outside >/dev/null
wait_healthy

got="$(cli "$CMO_APP_USER" "$CMO_APP_PASSWORD" GET cmo:smoke | tr -d '\r')"
[[ "$got" == "persisted" ]] || fail "value did not survive restart: '${got}'"

echo "smoke: ok (cmo_version marker present, auth required, app user restricted, data persisted)"
