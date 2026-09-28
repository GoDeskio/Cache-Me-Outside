#!/bin/sh
# Install-time check for the .deb. Generates passwords only when asked,
# starts the same program systemd runs, and does not print secrets.
set -eu

env_file="${CMO_ENV_FILE:-/etc/cache-me-outside/environment}"

rand_hex() {
    od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

if [ "${CMO_SMOKE_RESET_ENV:-0}" = "1" ] || [ ! -f "$env_file" ]; then
    admin="$(rand_hex)"
    app="$(rand_hex)"
    umask 077
    mkdir -p "$(dirname "$env_file")"
    cat > "$env_file" <<EOF
CMO_ADMIN_USER=admin
CMO_ADMIN_PASSWORD=${admin}
CMO_APP_USER=app
CMO_APP_PASSWORD=${app}
CMO_ROLE=standalone
CMO_BIND_ADDRESS=127.0.0.1
CMO_PORT=6379
CMO_MAXMEMORY=64mb
CMO_MAXMEMORY_POLICY=allkeys-lru
CMO_IO_THREADS=1
EOF
    chown root:valkey "$env_file"
    chmod 640 "$env_file"
    unset admin app
fi

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

pid=""
cleanup() {
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        /usr/lib/cache-me-outside/cmo-shutdown || true
        wait "$pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT

install -d -o valkey -g valkey -m 750 /run/cache-me-outside /var/lib/cache-me-outside
runuser --preserve-environment -u valkey -- /usr/lib/cache-me-outside/cmo-run >/tmp/cmo-native.log 2>&1 &
pid="$!"

ready=0
i=0
while [ "$i" -lt 40 ]; do
    if valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
        --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning PING 2>/dev/null | grep -q PONG; then
        ready=1
        break
    fi
    i=$((i + 1))
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    echo "native smoke: server did not answer" >&2
    cat /tmp/cmo-native.log >&2 || true
    exit 1
fi

unauth="$(valkey-cli -h 127.0.0.1 -p "$CMO_PORT" PING 2>&1 || true)"
case "$unauth" in
    *NOAUTH*) ;;
    *)
        echo "native smoke: unauthenticated PING was not rejected: ${unauth}" >&2
        exit 1
        ;;
esac

valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning \
    SET cmo:native ok >/dev/null
got="$(valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning \
    GET cmo:native | tr -d '\r')"
[ "$got" = "ok" ] || {
    echo "native smoke: GET returned '${got}'" >&2
    exit 1
}

denied="$(valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning \
    FLUSHALL 2>&1 || true)"
case "$denied" in
    *NOPERM*) ;;
    *)
        echo "native smoke: FLUSHALL was not denied: ${denied}" >&2
        exit 1
        ;;
esac

info="$(valkey-cli -h 127.0.0.1 -p "$CMO_PORT" \
    --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning INFO server)"
case "$info" in
    *"cmo_version:"*"-cmo"*) ;;
    *)
        echo "native smoke: missing cmo_version marker" >&2
        exit 1
        ;;
esac

ss_out="$(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true)"
case "$ss_out" in
    *"0.0.0.0:${CMO_PORT}"* | *"*:${CMO_PORT}"*)
        echo "native smoke: process is listening on every interface" >&2
        echo "$ss_out" >&2
        exit 1
        ;;
esac

/usr/lib/cache-me-outside/cmo-shutdown
wait "$pid" 2>/dev/null || true
pid=""
if [ ! -s /var/lib/cache-me-outside/dump.rdb ]; then
    echo "native smoke: SHUTDOWN SAVE did not write dump.rdb" >&2
    exit 1
fi

echo "native smoke: ok"
