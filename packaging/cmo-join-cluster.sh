#!/bin/sh
# Join this host to an existing cluster. No-op unless CMO_CLUSTER_SEED is set.
# Auth comes from the environment file. The password is not printed.
set -eu

env_file="${CMO_ENVIRONMENT_FILE:-/etc/cache-me-outside/environment}"
if [ -f "$env_file" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$env_file"
    set +a
fi

if [ -z "${CMO_CLUSTER_SEED:-}" ]; then
    exit 0
fi

refuse_wildcard() {
    case "$1" in
        "" | 0.0.0.0 | "::" | "*" | "[::]" | "0.0.0.0/0")
            echo "cmo-join-cluster: refusing wildcard address in $2" >&2
            exit 1
            ;;
    esac
}

user="${CMO_ADMIN_USER:-admin}"
port="${CMO_PORT:-6379}"
announce="${CMO_ANNOUNCE_IP:-}"
join_as="${CMO_CLUSTER_JOIN_AS:-primary}"
seed="$CMO_CLUSTER_SEED"
case "$seed" in
    *:*) ;;
    *)
        echo "cmo-join-cluster: CMO_CLUSTER_SEED must be host:port" >&2
        exit 1
        ;;
esac
seed_port="${seed##*:}"
seed_host="${seed%:*}"

refuse_wildcard "$seed_host" CMO_CLUSTER_SEED
refuse_wildcard "$announce" CMO_ANNOUNCE_IP
if [ -z "${CMO_ADMIN_PASSWORD:-}" ]; then
    echo "cmo-join-cluster: CMO_ADMIN_PASSWORD is not set" >&2
    exit 1
fi
if [ "$seed_host" = "$announce" ] && [ "$seed_port" = "$port" ]; then
    echo "cmo-join-cluster: CMO_CLUSTER_SEED must be a node that is already in the cluster" >&2
    exit 1
fi
case "$join_as" in
    primary) ;;
    replica)
        if [ -z "${CMO_CLUSTER_PRIMARY_ID:-}" ]; then
            echo "cmo-join-cluster: CMO_CLUSTER_PRIMARY_ID is required when joining as a replica" >&2
            exit 1
        fi
        ;;
    *)
        echo "cmo-join-cluster: CMO_CLUSTER_JOIN_AS must be primary or replica" >&2
        exit 1
        ;;
esac

export VALKEYCLI_AUTH="$CMO_ADMIN_PASSWORD"

ping_ok() {
    valkey-cli -h "$1" -p "$2" --user "$user" --no-auth-warning PING 2>/dev/null | grep -q PONG
}

i=0
while [ "$i" -lt 60 ]; do
    if ping_ok 127.0.0.1 "$port"; then
        break
    fi
    i=$((i + 1))
    sleep 1
done
ping_ok 127.0.0.1 "$port"

if valkey-cli -h "$seed_host" -p "$seed_port" --user "$user" --no-auth-warning CLUSTER NODES 2>/dev/null \
    | grep -F "${announce}:${port}" >/dev/null; then
    exit 0
fi

if [ "$join_as" = "replica" ]; then
    valkey-cli -h 127.0.0.1 -p "$port" --user "$user" --no-auth-warning \
        --cluster add-node "${announce}:${port}" "${seed_host}:${seed_port}" \
        --cluster-replica --cluster-primary-id "$CMO_CLUSTER_PRIMARY_ID" --cluster-yes
else
    valkey-cli -h 127.0.0.1 -p "$port" --user "$user" --no-auth-warning \
        --cluster add-node "${announce}:${port}" "${seed_host}:${seed_port}" --cluster-yes
fi

i=0
while [ "$i" -lt 30 ]; do
    if valkey-cli -h "$seed_host" -p "$seed_port" --user "$user" --no-auth-warning CLUSTER NODES 2>/dev/null \
        | grep -F "${announce}:${port}" >/dev/null; then
        break
    fi
    i=$((i + 1))
    sleep 2
done
valkey-cli -h "$seed_host" -p "$seed_port" --user "$user" --no-auth-warning CLUSTER NODES \
    | grep -F "${announce}:${port}" >/dev/null

if [ "$join_as" = "primary" ]; then
    valkey-cli -h "$seed_host" -p "$seed_port" --user "$user" --no-auth-warning \
        --cluster rebalance "${seed_host}:${seed_port}" \
        --cluster-use-empty-primaries --cluster-yes
fi

echo "cmo-join-cluster: ${announce}:${port} joined ${seed_host}:${seed_port} as ${join_as}"
