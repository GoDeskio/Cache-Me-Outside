#!/bin/sh
# Generate the ACL file from the environment, then start valkey-server.
# Passwords are never written into the image or the data volume.
set -eu

# Client tools skip ACL generation. `docker run --entrypoint valkey-cli` stays a client.
case "${1:-}" in
    valkey-cli | valkey-benchmark | valkey-check-rdb | valkey-check-aof | redis-cli)
        if [ "$(id -u)" = "0" ]; then
            exec gosu valkey "$@"
        fi
        exec "$@"
        ;;
    /bin/sh | sh | /bin/bash | bash)
        exec "$@"
        ;;
esac

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown valkey:valkey /data
    chmod 750 /data
    exec gosu valkey "$0" "$@"
fi

: "${CMO_ADMIN_USER:=admin}"
: "${CMO_ADMIN_PASSWORD:?Set CMO_ADMIN_PASSWORD in the environment or env file}"
: "${CMO_APP_USER:=app}"
: "${CMO_APP_PASSWORD:?Set CMO_APP_PASSWORD in the environment or env file}"
: "${CMO_MAXMEMORY:=256mb}"
: "${CMO_MAXMEMORY_POLICY:=allkeys-lru}"
: "${CMO_PORT:=6379}"
: "${CMO_CONTAINER_BIND:=0.0.0.0}"
: "${CMO_IO_THREADS:=1}"
: "${CMO_ROLE:=standalone}"
: "${CMO_CLUSTER_ENABLED:=no}"
: "${CMO_CLUSTER_NODE_TIMEOUT:=5000}"
: "${CMO_SENTINEL_MASTER:=cmo}"
: "${CMO_SENTINEL_QUORUM:=2}"
: "${CMO_SENTINEL_DOWN_AFTER_MS:=5000}"
: "${CMO_SENTINEL_FAILOVER_TIMEOUT:=60000}"
: "${CMO_SENTINEL_PARALLEL_SYNCS:=1}"

reject_placeholder() {
    case "$1" in
        *replace-with* | *CHANGE_ME* | *changeme* | *change-me*)
            echo "cache-me-outside: refusing placeholder secret in $2" >&2
            exit 1
            ;;
    esac
}

require_token() {
    # ACL lines are space-separated. Keep secrets and names to a single token.
    case "$1" in
        "" | *[!A-Za-z0-9_./+=@-]*)
            echo "cache-me-outside: $2 contains unsupported characters" >&2
            exit 1
            ;;
    esac
}

require_password() {
    require_token "$1" "$2"
    reject_placeholder "$1" "$2"
    if [ "${#1}" -lt 16 ]; then
        echo "cache-me-outside: $2 must be at least 16 characters" >&2
        exit 1
    fi
}

require_user() {
    case "$1" in
        [A-Za-z] | [A-Za-z][A-Za-z0-9_-]*)
            ;;
        *)
            echo "cache-me-outside: $2 must start with a letter" >&2
            exit 1
            ;;
    esac
    case "$1" in
        *[!A-Za-z0-9_-]*)
            echo "cache-me-outside: $2 contains unsupported characters" >&2
            exit 1
            ;;
    esac
    if [ "$1" = "default" ]; then
        echo "cache-me-outside: $2 cannot be 'default'" >&2
        exit 1
    fi
}

case "$CMO_MAXMEMORY_POLICY" in
    allkeys-lru | allkeys-lfu | allkeys-random | volatile-lru | volatile-lfu | volatile-random | volatile-ttl | noeviction)
        ;;
    *)
        echo "cache-me-outside: unsupported maxmemory policy: $CMO_MAXMEMORY_POLICY" >&2
        exit 1
        ;;
esac

case "$CMO_MAXMEMORY" in
    *[!0-9A-Za-z]*)
        echo "cache-me-outside: unsupported maxmemory value: $CMO_MAXMEMORY" >&2
        exit 1
        ;;
esac

case "$CMO_PORT" in
    '' | *[!0-9]*)
        echo "cache-me-outside: CMO_PORT must be numeric" >&2
        exit 1
        ;;
esac

case "$CMO_CONTAINER_BIND" in
    *[!A-Za-z0-9.:-]*)
        echo "cache-me-outside: unsupported CMO_CONTAINER_BIND" >&2
        exit 1
        ;;
esac

case "$CMO_IO_THREADS" in
    '' | *[!0-9]*)
        echo "cache-me-outside: CMO_IO_THREADS must be an integer" >&2
        exit 1
        ;;
esac
if [ "$CMO_IO_THREADS" -lt 1 ] || [ "$CMO_IO_THREADS" -gt 128 ]; then
    echo "cache-me-outside: CMO_IO_THREADS must be from 1 to 128" >&2
    exit 1
fi

case "$CMO_CLUSTER_ENABLED" in
    yes | no) ;;
    *)
        echo "cache-me-outside: CMO_CLUSTER_ENABLED must be yes or no" >&2
        exit 1
        ;;
esac

# Pod names in Kubernetes end in -0 for the initial primary. Compose sets an explicit role.
if [ "$CMO_ROLE" = "auto" ]; then
    case "${HOSTNAME:-}" in
        *-0) CMO_ROLE=primary ;;
        *) CMO_ROLE=replica ;;
    esac
fi

case "$CMO_ROLE" in
    standalone | primary | replica | sentinel | cluster) ;;
    *)
        echo "cache-me-outside: unsupported CMO_ROLE: $CMO_ROLE" >&2
        exit 1
        ;;
esac

if [ "$CMO_ROLE" = "cluster" ]; then
    CMO_CLUSTER_ENABLED=yes
fi

refuse_announce() {
    case "$1" in
        "" | 0.0.0.0 | "::" | "*" | "[::]")
            echo "cache-me-outside: $2 must be one reachable address, not $1" >&2
            exit 1
            ;;
    esac
}

if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
    refuse_announce "$CMO_ANNOUNCE_IP" CMO_ANNOUNCE_IP
    case "$CMO_ANNOUNCE_IP" in
        *[!A-Za-z0-9.:-]*)
            echo "cache-me-outside: unsupported CMO_ANNOUNCE_IP" >&2
            exit 1
            ;;
    esac
fi

require_user "$CMO_ADMIN_USER" CMO_ADMIN_USER
require_user "$CMO_APP_USER" CMO_APP_USER
require_password "$CMO_ADMIN_PASSWORD" CMO_ADMIN_PASSWORD
require_password "$CMO_APP_PASSWORD" CMO_APP_PASSWORD

if [ "$CMO_ADMIN_USER" = "$CMO_APP_USER" ]; then
    echo "cache-me-outside: admin and app users must be different" >&2
    exit 1
fi
if [ "$CMO_ADMIN_PASSWORD" = "$CMO_APP_PASSWORD" ]; then
    echo "cache-me-outside: admin and app passwords must be different" >&2
    exit 1
fi

umask 077
# ACL files accept only "user" and "role" lines. Comments are rejected.
# Sentinel subcommands exist only in sentinel mode, so the discovery allows
# are added only there. Data nodes keep the app user out of @admin entirely.
# Sentinel mode does not register data commands, so naming them in the ACL
# aborts startup. Discovery subcommands are allowed only on sentinels.
if [ "$CMO_ROLE" = "sentinel" ]; then
    app_acl="+@all -@dangerous -@admin +sentinel|get-master-addr-by-name +sentinel|get-primary-addr-by-name +sentinel|sentinels +sentinel|replicas +sentinel|slaves +sentinel|masters +sentinel|primaries"
else
    app_acl="+@all -@dangerous -@admin -flushall -flushdb -debug -config -keys -shutdown -module -acl -replicaof -slaveof -migrate -restore -sort -failover -bgsave -bgrewriteaof -save -monitor -sync -psync"
fi
cat > /tmp/cmo-users.acl <<EOF
user default reset
user ${CMO_ADMIN_USER} on >${CMO_ADMIN_PASSWORD} ~* &* +@all
user ${CMO_APP_USER} on >${CMO_APP_PASSWORD} ~* &* ${app_acl}
EOF
chmod 600 /tmp/cmo-users.acl

if [ "$CMO_ROLE" = "sentinel" ]; then
    : "${CMO_PRIMARY_HOST:?Set CMO_PRIMARY_HOST for a sentinel}"
    : "${CMO_PRIMARY_PORT:=6379}"
    umask 077
    {
        printf '%s\n' "bind ${CMO_CONTAINER_BIND}"
        printf '%s\n' "port ${CMO_PORT}"
        printf '%s\n' "protected-mode yes"
        printf '%s\n' "daemonize no"
        printf '%s\n' "supervised no"
        printf '%s\n' "logfile \"\""
        printf '%s\n' "dir /tmp"
        printf '%s\n' "aclfile /tmp/cmo-users.acl"
        printf '%s\n' "sentinel monitor ${CMO_SENTINEL_MASTER} ${CMO_PRIMARY_HOST} ${CMO_PRIMARY_PORT} ${CMO_SENTINEL_QUORUM}"
        printf '%s\n' "sentinel auth-user ${CMO_SENTINEL_MASTER} ${CMO_ADMIN_USER}"
        printf '%s\n' "sentinel auth-pass ${CMO_SENTINEL_MASTER} ${CMO_ADMIN_PASSWORD}"
        printf '%s\n' "sentinel down-after-milliseconds ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_DOWN_AFTER_MS}"
        printf '%s\n' "sentinel failover-timeout ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_FAILOVER_TIMEOUT}"
        printf '%s\n' "sentinel parallel-syncs ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_PARALLEL_SYNCS}"
        printf '%s\n' "sentinel resolve-hostnames yes"
        printf '%s\n' "sentinel announce-hostnames yes"
        printf '%s\n' "sentinel sentinel-user ${CMO_ADMIN_USER}"
        printf '%s\n' "sentinel sentinel-pass ${CMO_ADMIN_PASSWORD}"
        if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
            printf '%s\n' "sentinel announce-ip ${CMO_ANNOUNCE_IP}"
            printf '%s\n' "sentinel announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
        fi
    } > /tmp/cmo-sentinel.conf
    chmod 600 /tmp/cmo-sentinel.conf
    exec valkey-sentinel /tmp/cmo-sentinel.conf "$@"
fi

replica_host=""
replica_port=""
if [ "$CMO_ROLE" = "replica" ]; then
    if [ -n "${CMO_REPLICAOF:-}" ]; then
        # Accept "host port" or "host:port".
        replica_host="${CMO_REPLICAOF%%:*}"
        replica_port="${CMO_REPLICAOF#*:}"
        if [ "$replica_host" = "$CMO_REPLICAOF" ]; then
            replica_host="${CMO_REPLICAOF%% *}"
            replica_port="${CMO_REPLICAOF#* }"
        fi
    else
        : "${CMO_PRIMARY_HOST:?Set CMO_PRIMARY_HOST or CMO_REPLICAOF for a replica}"
        replica_host="$CMO_PRIMARY_HOST"
        replica_port="${CMO_PRIMARY_PORT:-6379}"
    fi
fi

umask 077
{
    printf '%s\n' "include /etc/cache-me-outside/valkey.conf"
    printf '%s\n' "bind ${CMO_CONTAINER_BIND}"
    printf '%s\n' "port ${CMO_PORT}"
    printf '%s\n' "maxmemory ${CMO_MAXMEMORY}"
    printf '%s\n' "maxmemory-policy ${CMO_MAXMEMORY_POLICY}"
    printf '%s\n' "io-threads ${CMO_IO_THREADS}"
    if [ "$CMO_CLUSTER_ENABLED" = "yes" ] || [ -n "$replica_host" ]; then
        # Replicas and cluster nodes authenticate replication as the admin user.
        # The app user cannot SYNC/PSYNC.
        printf '%s\n' "masteruser ${CMO_ADMIN_USER}"
        printf '%s\n' "masterauth ${CMO_ADMIN_PASSWORD}"
    fi
    if [ -n "$replica_host" ]; then
        printf '%s\n' "replicaof ${replica_host} ${replica_port}"
        if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
            printf '%s\n' "replica-announce-ip ${CMO_ANNOUNCE_IP}"
            printf '%s\n' "replica-announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
        fi
    fi
    if [ "$CMO_CLUSTER_ENABLED" = "yes" ]; then
        printf '%s\n' "cluster-enabled yes"
        printf '%s\n' "cluster-config-file /data/nodes.conf"
        printf '%s\n' "cluster-node-timeout ${CMO_CLUSTER_NODE_TIMEOUT}"
        if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
            printf '%s\n' "cluster-announce-ip ${CMO_ANNOUNCE_IP}"
            printf '%s\n' "cluster-announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
            printf '%s\n' "cluster-announce-bus-port ${CMO_ANNOUNCE_BUS_PORT:-$((CMO_PORT + 10000))}"
            printf '%s\n' "cluster-preferred-endpoint-type ip"
        elif [ -n "${CMO_ANNOUNCE_HOSTNAME:-}" ]; then
            printf '%s\n' "cluster-announce-hostname ${CMO_ANNOUNCE_HOSTNAME}"
            printf '%s\n' "cluster-preferred-endpoint-type hostname"
        fi
    fi
} > /tmp/cmo-runtime.conf
chmod 600 /tmp/cmo-runtime.conf

exec valkey-server /tmp/cmo-runtime.conf "$@"
