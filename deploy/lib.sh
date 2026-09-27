#!/usr/bin/env bash
# Shared helpers for Cache-Me-Outside deploy scripts. Source this file.
# It does not start containers.

cmo_deploy_dir() {
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
}

cmo_load_env() {
    local dir
    dir="$(cmo_deploy_dir)"
    if [[ ! -f "$dir/.env" ]]; then
        echo "Missing deploy/.env." >&2
        echo "Copy cache-me-outside.env.example to .env, replace both passwords, and chmod 600 .env." >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1091
    source "$dir/.env"
    set +a
    : "${CMO_ADMIN_USER:=admin}"
    : "${CMO_APP_USER:=app}"
    : "${CMO_PORT:=6379}"
    : "${CMO_BIND_ADDRESS:=127.0.0.1}"
    : "${CMO_HOST_PORT:=6379}"
    : "${CMO_MAXMEMORY:=256mb}"
    : "${CMO_MAXMEMORY_POLICY:=allkeys-lru}"
    : "${CMO_CONTAINER_MEMORY:=512m}"
    : "${CMO_CPUS:=1.0}"
    : "${CMO_IO_THREADS:=1}"
    : "${CMO_REPLICAS:=2}"
    : "${CMO_SENTINELS:=3}"
    : "${CMO_CLUSTER_PRIMARIES:=3}"
    : "${CMO_CLUSTER_REPLICAS:=1}"
    : "${CMO_SENTINEL_PORT:=26379}"
    : "${CMO_SENTINEL_MASTER:=cmo}"
}

# Refuse a host publish address that would listen on every interface.
cmo_refuse_wildcard_bind() {
    local address="$1"
    local label="${2:-CMO_BIND_ADDRESS}"
    case "$address" in
        "" | 0.0.0.0 | "::" | "*" | "[::]" | "0.0.0.0/0")
            echo "Refusing to publish Cache-Me-Outside on all host interfaces (${address})." >&2
            echo "Set ${label} to 127.0.0.1 or one reachable address." >&2
            exit 1
            ;;
    esac
}

# Valkey memory units (mb = 1024*1024, m = 1000*1000). Prints bytes.
cmo_mem_to_bytes() {
    local raw="${1,,}" num unit
    if [[ ! "$raw" =~ ^([0-9]+)([a-z]*)$ ]]; then
        echo "Unsupported memory size: $1" >&2
        return 1
    fi
    num="${BASH_REMATCH[1]}"
    unit="${BASH_REMATCH[2]}"
    case "$unit" in
        "" | b) echo "$num" ;;
        k) echo $((num * 1000)) ;;
        kb) echo $((num * 1024)) ;;
        m) echo $((num * 1000 * 1000)) ;;
        mb) echo $((num * 1024 * 1024)) ;;
        g) echo $((num * 1000 * 1000 * 1000)) ;;
        gb) echo $((num * 1024 * 1024 * 1024)) ;;
        *)
            echo "Unsupported memory size: $1" >&2
            return 1
            ;;
    esac
}

cmo_admin() {
    local container="$1"
    shift
    docker exec "$container" \
        valkey-cli -h 127.0.0.1 -p "${CMO_PORT:-6379}" \
        --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning \
        "$@"
}

cmo_app() {
    local container="$1"
    shift
    local cluster=()
    if [[ "${CMO_CLI_CLUSTER:-0}" == "1" ]]; then
        cluster=(-c)
    fi
    docker exec "$container" \
        valkey-cli -h 127.0.0.1 -p "${CMO_PORT:-6379}" \
        "${cluster[@]}" \
        --user "$CMO_APP_USER" -a "$CMO_APP_PASSWORD" --no-auth-warning \
        "$@"
}

cmo_admin_port() {
    local container="$1"
    local port="$2"
    shift 2
    docker exec "$container" \
        valkey-cli -h 127.0.0.1 -p "$port" \
        --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning \
        "$@"
}

# Cluster manager commands run inside the network so node names resolve.
cmo_cluster_mgr() {
    local container="$1"
    shift
    docker exec "$container" \
        valkey-cli --user "$CMO_ADMIN_USER" -a "$CMO_ADMIN_PASSWORD" --no-auth-warning \
        --cluster "$@"
}

# Gossip needs a moment after CLUSTER MEET. valkey-cli --cluster rebalance
# refuses to run until every node reports the same slot map.
cmo_wait_cluster_agreement() {
    local expect="$1"
    shift
    local i name info known state sig first ok
    for i in $(seq 1 40); do
        first=""
        ok=1
        for name in "$@"; do
            info="$(cmo_admin "$name" CLUSTER INFO 2>/dev/null || true)"
            known="$(printf '%s\n' "$info" | awk -F: '/^cluster_known_nodes:/ { gsub(/\r/, "", $2); print $2 }')"
            state="$(printf '%s\n' "$info" | awk -F: '/^cluster_state:/ { gsub(/\r/, "", $2); print $2 }')"
            sig="$(cmo_admin "$name" CLUSTER NODES 2>/dev/null | awk '{
                slots = ""
                for (n = 9; n <= NF; n++) slots = slots $n
                if (slots != "") print $1, slots
            }' | sort | tr '\n' ';')"
            if [[ "$known" != "$expect" || "$state" != "ok" || -z "$sig" ]]; then
                ok=0
                break
            fi
            if [[ -z "$first" ]]; then
                first="$sig"
            elif [[ "$sig" != "$first" ]]; then
                ok=0
                break
            fi
        done
        if [[ "$ok" -eq 1 ]]; then
            return 0
        fi
        sleep 1
    done
    echo "cluster nodes did not agree on membership and slots" >&2
    return 1
}

cmo_wait_healthy() {
    local container="$1"
    local status="" i
    for i in $(seq 1 90); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container" 2>/dev/null || true)"
        if [[ "$status" == "healthy" ]]; then
            return 0
        fi
        sleep 1
    done
    echo "container ${container} did not become healthy (last status: ${status:-missing})" >&2
    docker logs --tail 80 "$container" >&2 || true
    return 1
}

cmo_generated_dir() {
    echo "$(cmo_deploy_dir)/.generated"
}

cmo_compose() {
    local dir gen
    dir="$(cmo_deploy_dir)"
    gen="$(cmo_generated_dir)/compose.yml"
    if [[ -f "$gen" && "${CMO_TOPOLOGY:-standalone}" != "standalone" && "${CMO_TOPOLOGY:-}" != "node" ]]; then
        docker compose --project-directory "$dir" -p cache-me-outside -f "$gen" "$@"
    elif [[ "${CMO_TOPOLOGY:-standalone}" == "node" ]]; then
        docker compose --project-directory "$dir" -p cache-me-outside -f "$dir/docker-compose.node.yml" "$@"
    else
        docker compose --project-directory "$dir" -p cache-me-outside -f "$dir/docker-compose.yml" "$@"
    fi
}
