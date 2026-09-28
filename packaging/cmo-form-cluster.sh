#!/bin/sh
# Create a cluster from host:port arguments. Skips when the first node is already up.
# Auth: CMO_ADMIN_USER and VALKEYCLI_AUTH. The password is not printed.
# CMO_CLUSTER_REPLICAS is the replica count passed to --cluster create (default 0).
set -eu

if [ "$#" -lt 3 ]; then
    echo "cmo-form-cluster: need at least 3 host:port arguments" >&2
    exit 1
fi

refuse_wildcard() {
    case "$1" in
        "" | 0.0.0.0 | "::" | "*" | "[::]" | "0.0.0.0/0")
            echo "cmo-form-cluster: refusing wildcard address" >&2
            exit 1
            ;;
    esac
}

user="${CMO_ADMIN_USER:-admin}"
replicas="${CMO_CLUSTER_REPLICAS:-0}"
if [ -z "${VALKEYCLI_AUTH:-}" ]; then
    echo "cmo-form-cluster: VALKEYCLI_AUTH is not set" >&2
    exit 1
fi

for node in "$@"; do
    case "$node" in
        *:*) ;;
        *)
            echo "cmo-form-cluster: ${node} must be host:port" >&2
            exit 1
            ;;
    esac
    host="${node%:*}"
    refuse_wildcard "$host"
done

for node in "$@"; do
    host="${node%:*}"
    port="${node##*:}"
    i=0
    while [ "$i" -lt 60 ]; do
        if valkey-cli -h "$host" -p "$port" --user "$user" --no-auth-warning PING 2>/dev/null | grep -q PONG; then
            break
        fi
        i=$((i + 1))
        sleep 1
    done
    if ! valkey-cli -h "$host" -p "$port" --user "$user" --no-auth-warning PING 2>/dev/null | grep -q PONG; then
        echo "cmo-form-cluster: ${node} did not answer PING" >&2
        exit 1
    fi
done

first="$1"
first_port="${first##*:}"
first_host="${first%:*}"
if valkey-cli -h "$first_host" -p "$first_port" --user "$user" --no-auth-warning CLUSTER INFO 2>/dev/null \
    | grep -q 'cluster_state:ok'; then
    echo "cmo-form-cluster: already up"
    exit 0
fi

valkey-cli -h "$first_host" -p "$first_port" --user "$user" --no-auth-warning \
    --cluster create "$@" --cluster-replicas "$replicas" --cluster-yes

if ! valkey-cli -h "$first_host" -p "$first_port" --user "$user" --no-auth-warning CLUSTER INFO \
    | grep -q 'cluster_state:ok'; then
    echo "cmo-form-cluster: cluster_state is not ok" >&2
    exit 1
fi
echo "cmo-form-cluster: created $# nodes"
