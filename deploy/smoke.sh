#!/usr/bin/env bash
# Verify auth, the restricted app user, persistence, and the -cmo marker.
#   ./smoke.sh                  standalone
#   ./smoke.sh sentinel
#   ./smoke.sh cluster          uses a cluster-aware client
#   ./smoke.sh --generate-env   write deploy/.env when it is missing
#   ./smoke.sh --no-up          check a stack that is already running
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

generate_env=0
no_up=0
topology="${CMO_TOPOLOGY:-standalone}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --generate-env) generate_env=1 ;;
        --no-up) no_up=1 ;;
        standalone | sentinel | cluster) topology="$1" ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
    shift
done
export CMO_TOPOLOGY="$topology"

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
CMO_CPUS=1.0
CMO_IO_THREADS=1
EOF
    chmod 600 .env
    unset admin_password app_password
    echo "Wrote deploy/.env with generated passwords. The passwords were not printed."
fi

if [[ "$no_up" -eq 0 ]]; then
    ./up.sh "$topology"
fi

cmo_load_env
export CMO_TOPOLOGY="$topology"
if [[ "$topology" == "cluster" ]]; then
    export CMO_CLI_CLUSTER=1
fi

case "$topology" in
    standalone) container="cache-me-outside" ;;
    sentinel) container="cmo-primary" ;;
    cluster) container="cmo-cluster-0" ;;
    *)
        echo "smoke.sh does not target topology ${topology}" >&2
        exit 1
        ;;
esac

fail() {
    echo "smoke: $*" >&2
    docker logs --tail 80 "$container" >&2 || true
    exit 1
}

expect_noper() {
    local command_name="$1"
    shift
    local out
    out="$(cmo_app "$container" "$@" 2>&1 || true)"
    case "$out" in
        *NOPERM*) ;;
        *) fail "${command_name} was not denied for the app user: ${out}" ;;
    esac
}

data_nodes() {
    if [[ "$topology" == "standalone" ]]; then
        echo "$container"
        return
    fi
    # shellcheck disable=SC1091
    source .generated/state
    local spec
    for spec in "${nodes[@]}"; do
        # shellcheck disable=SC2086
        set -- $spec
        echo "$1"
    done
}

cmo_wait_healthy "$container"

published="$(docker port "$container")"
if [[ -z "$published" ]]; then
    fail "container ports are not published"
fi
if printf '%s\n' "$published" | grep -Eq '(^| )(0\.0\.0\.0|\[::\]|::):'; then
    fail "host port is published on all interfaces: ${published}"
fi

unauth="$(docker exec "$container" valkey-cli -h 127.0.0.1 -p "$CMO_PORT" PING 2>&1 || true)"
case "$unauth" in
    *NOAUTH*) ;;
    *) fail "unauthenticated PING was not rejected: ${unauth}" ;;
esac

cmo_app "$container" SET cmo:smoke persisted >/dev/null
got="$(cmo_app "$container" GET cmo:smoke | tr -d '\r')"
[[ "$got" == "persisted" ]] || fail "GET returned '${got}'"
sleep 2

expect_noper FLUSHALL FLUSHALL
expect_noper FLUSHDB FLUSHDB
expect_noper CONFIG CONFIG GET maxmemory
expect_noper KEYS KEYS '*'

debug_out="$(cmo_app "$container" DEBUG SLEEP 0 2>&1 || true)"
case "$debug_out" in
    *NOPERM* | *"DEBUG command not allowed"*) ;;
    *) fail "DEBUG was not denied for the app user: ${debug_out}" ;;
esac

protected="$(cmo_admin "$container" CONFIG GET protected-mode 2>&1 || true)"
case "$protected" in
    *NOPERM*) fail "admin user cannot read config" ;;
    *yes*) ;;
    *) fail "protected-mode is not yes: ${protected}" ;;
esac

info="$(cmo_admin "$container" INFO server)"
case "$info" in
    *"cmo_version:"*"-cmo"*) ;;
    *) fail "INFO server is missing the -cmo marker" ;;
esac
version="$(printf '%s\n' "$info" | awk -F: '/^valkey_version:/{gsub(/\r/, "", $2); print $2}')"
case "$version" in
    "" | *-* | *[!0-9.]*) fail "valkey_version is not a numeric major.minor.patch value: '${version}'" ;;
esac

if [[ "$topology" == "standalone" ]]; then
    # The default 256mb cache sits at half of the 512m limit. Grow the cgroup
    # first, then raise maxmemory live. A decrease and an over-half value must fail.
    docker update --memory 768m --memory-swap 768m "$container" >/dev/null
    ./scale-memory.sh 320mb "$container" >/dev/null
    applied="$(cmo_admin "$container" CONFIG GET maxmemory | awk 'NR==2 { gsub(/\r/, "", $1); print $1 }')"
    [[ "$applied" == "$((320 * 1024 * 1024))" ]] || fail "live maxmemory was not raised (${applied})"
    if ./scale-memory.sh 1mb "$container" >/dev/null 2>&1; then
        fail "scale-memory.sh accepted a decrease"
    fi
    if ./scale-memory.sh 400mb "$container" >/dev/null 2>&1; then
        fail "scale-memory.sh accepted a value above half the container limit"
    fi
    # Later topologies read .env. Put the documented default back; this process
    # keeps the live 320mb until it is recreated.
    sed -i 's/^CMO_MAXMEMORY=.*/CMO_MAXMEMORY=256mb/' .env
fi

sleep 2
while IFS= read -r node; do
    cmo_admin "$node" BGSAVE >/dev/null || true
done < <(data_nodes)

saved=0
for _i in $(seq 1 30); do
    saved=1
    while IFS= read -r node; do
        if ! docker exec "$node" sh -c 'test -s /data/dump.rdb && test -d /data/appendonlydir'; then
            saved=0
        fi
    done < <(data_nodes)
    if [[ "$saved" -eq 1 ]]; then
        break
    fi
    sleep 1
done
[[ "$saved" -eq 1 ]] || fail "RDB snapshot or AOF directory is missing on a data volume"

if [[ "$topology" == "standalone" ]]; then
    docker compose --project-directory "$(pwd)" -p cache-me-outside -f docker-compose.yml restart "$container" >/dev/null
else
    docker compose --project-directory "$(pwd)" -p cache-me-outside -f .generated/compose.yml restart >/dev/null
fi
cmo_wait_healthy "$container"
if [[ "$topology" == "cluster" ]]; then
    ok=0
    for _i in $(seq 1 60); do
        if cmo_admin "$container" CLUSTER INFO | grep -q 'cluster_state:ok'; then
            ok=1
            break
        fi
        sleep 1
    done
    [[ "$ok" -eq 1 ]] || fail "cluster did not recover after restart"
fi

got="$(cmo_app "$container" GET cmo:smoke | tr -d '\r')"
[[ "$got" == "persisted" ]] || fail "value did not survive restart: '${got}'"

echo "smoke: ok (${topology}, cmo_version marker present, auth required, app user restricted, data persisted)"
