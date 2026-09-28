#!/usr/bin/env bash
# Shared helpers for Cache-Me-Outside deploy scripts. Source this file.
# It does not start containers.

cmo_deploy_dir() {
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
}

# Absolute path, or a path relative to deploy/. Override with CMO_ENV_FILE
# when the file lives outside the repo (a vault directory, for example).
cmo_env_path() {
    local dir
    dir="$(cmo_deploy_dir)"
    if [[ -n "${CMO_ENV_FILE:-}" ]]; then
        case "$CMO_ENV_FILE" in
            /*) printf '%s\n' "$CMO_ENV_FILE" ;;
            *) printf '%s\n' "${dir}/${CMO_ENV_FILE}" ;;
        esac
    else
        printf '%s\n' "${dir}/.env"
    fi
}

# Compose project, Docker network, and container/volume prefix.
# Defaults keep a standalone container named cache-me-outside.
# Test scripts switch these to cmo-test unless --i-know is passed.
cmo_apply_names() {
    : "${CMO_PROJECT:=cache-me-outside}"
    : "${CMO_NETWORK:=cache-me-outside}"
    : "${CMO_NAME_PREFIX:=cache-me-outside}"
    : "${CMO_PRODUCTION_PROJECT:=cache-me-outside}"
    local name label
    for label in CMO_PROJECT CMO_NETWORK CMO_NAME_PREFIX CMO_PRODUCTION_PROJECT; do
        name="${!label}"
        case "$name" in
            [a-z0-9]* ) ;;
            *)
                echo "${label} must start with a letter or digit: ${name}" >&2
                exit 1
                ;;
        esac
        case "$name" in
            *[!a-z0-9_-]* | *- | *_ )
                echo "${label} may only use lowercase letters, digits, '_' and '-': ${name}" >&2
                exit 1
                ;;
        esac
    done
    if [[ -n "${CMO_SUBNET:-}" ]]; then
        cmo_refuse_subnet "$CMO_SUBNET"
    fi
    export CMO_PROJECT CMO_NETWORK CMO_NAME_PREFIX CMO_PRODUCTION_PROJECT
}

cmo_standalone_name() {
    cmo_apply_names
    printf '%s\n' "$CMO_NAME_PREFIX"
}

cmo_member_name() {
    cmo_apply_names
    printf '%s-%s\n' "$CMO_NAME_PREFIX" "$1"
}

# Test scripts call this before they load the env file or delete anything.
# Unset names become the cmo-test project. The production project is refused
# unless the caller passed --i-know (recorded in CMO_TEST_ALLOW).
cmo_prepare_test_identity() {
    local arg
    CMO_TEST_ALLOW=0
    for arg in "$@"; do
        if [[ "$arg" == "--i-know" ]]; then
            CMO_TEST_ALLOW=1
        fi
    done
    export CMO_TEST_ALLOW
    : "${CMO_PROJECT:=cmo-test}"
    : "${CMO_NETWORK:=cmo-test}"
    : "${CMO_NAME_PREFIX:=cmo-test}"
    export CMO_PROJECT CMO_NETWORK CMO_NAME_PREFIX
    cmo_test_guard
}

cmo_test_guard() {
    [[ "${CMO_TEST_ALLOW:-}" == "0" || "${CMO_TEST_ALLOW:-}" == "1" ]] || return 0
    [[ "${CMO_TEST_ALLOW}" == "1" ]] && return 0
    cmo_apply_names
    local prod="$CMO_PRODUCTION_PROJECT"
    if [[ "$CMO_PROJECT" == "$prod" || "$CMO_NETWORK" == "$prod" || "$CMO_NAME_PREFIX" == "$prod" ||
        "$CMO_PROJECT" == "cache-me-outside" || "$CMO_NETWORK" == "cache-me-outside" || "$CMO_NAME_PREFIX" == "cache-me-outside" ]]; then
        echo "Refusing to run tests against project '${CMO_PROJECT}' network '${CMO_NETWORK}' prefix '${CMO_NAME_PREFIX}'." >&2
        echo "Tests use cmo-test unless you pass --i-know. That flag can delete a live deployment." >&2
        exit 1
    fi
}

cmo_refuse_subnet() {
    local subnet="$1" ip prefix o1 o2 o3 o4
    if [[ ! "$subnet" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9]+)$ ]]; then
        echo "CMO_SUBNET must be an IPv4 CIDR such as 203.0.113.0/24." >&2
        exit 1
    fi
    o1="${BASH_REMATCH[1]}"
    o2="${BASH_REMATCH[2]}"
    o3="${BASH_REMATCH[3]}"
    o4="${BASH_REMATCH[4]}"
    prefix="${BASH_REMATCH[5]}"
    for ip in "$o1" "$o2" "$o3" "$o4"; do
        if ((ip > 255)); then
            echo "CMO_SUBNET has an octet above 255: ${subnet}" >&2
            exit 1
        fi
    done
    if ((prefix < 8 || prefix > 28)); then
        echo "CMO_SUBNET prefix must be between /8 and /28." >&2
        exit 1
    fi
    if [[ "$subnet" == "0.0.0.0/0" ]]; then
        echo "Refusing CMO_SUBNET 0.0.0.0/0." >&2
        exit 1
    fi
}

cmo_subnet_file() {
    echo "$(cmo_generated_dir)/subnet.yml"
}

cmo_write_subnet_file() {
    [[ -n "${CMO_SUBNET:-}" ]] || return 0
    local file
    file="$(cmo_subnet_file)"
    mkdir -p "$(dirname "$file")"
    cat > "$file" <<EOF
# Generated from CMO_SUBNET. Do not commit.
networks:
  cmo:
    name: ${CMO_NETWORK}
    ipam:
      config:
        - subnet: ${CMO_SUBNET}
EOF
}

# Compose interpolation uses --env-file. The service env_file is separate and
# may be required: false so a missing path does not abort `compose config`.
cmo_dc() {
    cmo_apply_names
    local dir path
    local -a lead=()
    local -a tail=()
    dir="$(cmo_deploy_dir)"
    path="$(cmo_env_path)"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -f | --file)
                lead+=(-f "$2")
                shift 2
                ;;
            *)
                tail+=("$1")
                shift
                ;;
        esac
    done
    if [[ -n "${CMO_SUBNET:-}" ]]; then
        cmo_write_subnet_file
        lead+=(-f "$(cmo_subnet_file)")
    fi
    local -a args=(docker compose --project-directory "$dir" -p "$CMO_PROJECT")
    if [[ -f "$path" ]]; then
        args+=(--env-file "$path")
    fi
    "${args[@]}" "${lead[@]}" "${tail[@]}"
}

cmo_refuse_generic_alias() {
    local alias_name="${1:-}"
    case "$alias_name" in
        redis | valkey | REDIS | VALKEY)
            echo "Refusing network alias '${alias_name}'." >&2
            echo "That name collides with other stacks. Use a project-specific alias (default cache-me-outside)." >&2
            exit 1
            ;;
    esac
}

cmo_load_env() {
    local env_file
    env_file="$(cmo_env_path)"
    if [[ ! -f "$env_file" ]]; then
        echo "Missing ${env_file}." >&2
        echo "Copy cache-me-outside.env.example to deploy/.env, or set CMO_ENV_FILE to a file outside the repo." >&2
        echo "Replace both passwords and chmod 600 the file." >&2
        exit 1
    fi
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    # A test script may have selected cmo-test. The env file must not silently
    # point that script back at the production project.
    if [[ -n "${CMO_TEST_ALLOW:-}" ]]; then
        cmo_test_guard
    fi
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
cmo_cluster_user() {
    if [[ -n "${CMO_CLUSTER_USER:-}" ]]; then
        printf '%s\n' "$CMO_CLUSTER_USER"
    else
        printf '%s\n' "$CMO_ADMIN_USER"
    fi
}

cmo_cluster_password() {
    if [[ -n "${CMO_CLUSTER_USER:-}" ]]; then
        printf '%s\n' "${CMO_CLUSTER_PASSWORD:?Set CMO_CLUSTER_PASSWORD with CMO_CLUSTER_USER}"
    else
        printf '%s\n' "$CMO_ADMIN_PASSWORD"
    fi
}

cmo_cluster_mgr() {
    local container="$1"
    shift
    docker exec "$container" \
        valkey-cli --user "$(cmo_cluster_user)" -a "$(cmo_cluster_password)" --no-auth-warning \
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
    cmo_apply_names
    echo "$(cmo_deploy_dir)/.generated/${CMO_PROJECT}"
}

cmo_state_file() {
    echo "$(cmo_generated_dir)/state"
}

cmo_compose_file() {
    echo "$(cmo_generated_dir)/compose.yml"
}

cmo_compose() {
    local gen
    gen="$(cmo_generated_dir)/compose.yml"
    if [[ -f "$gen" && "${CMO_TOPOLOGY:-standalone}" != "standalone" && "${CMO_TOPOLOGY:-}" != "node" ]]; then
        cmo_dc -f "$gen" "$@"
    elif [[ "${CMO_TOPOLOGY:-standalone}" == "node" ]]; then
        cmo_dc -f "$(cmo_deploy_dir)/docker-compose.node.yml" "$@"
    else
        cmo_dc -f "$(cmo_deploy_dir)/docker-compose.yml" "$@"
    fi
}
