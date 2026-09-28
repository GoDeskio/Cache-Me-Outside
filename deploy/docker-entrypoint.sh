#!/bin/sh
# Generate the ACL file from the environment, then start valkey-server.
# Passwords are never written into the image. The ACL file lives in the runtime
# directory. Sentinel keeps its rewritten config there too, so a Sentinel whose
# runtime directory is the data volume stores its auth lines on that volume.
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

# Docker keeps data on the volume and writes the ACL under /tmp.
# The VM unit sets both to /var/lib and /run before it execs this script.
: "${CMO_DATA_DIR:=/data}"
: "${CMO_RUNTIME_DIR:=/tmp}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$CMO_DATA_DIR"
    chown valkey:valkey "$CMO_DATA_DIR"
    chmod 750 "$CMO_DATA_DIR"
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

# Optional accounts. Unset keeps replication, Sentinel, and cluster tooling on admin.
distinct_account() {
    if [ "$2" = "$CMO_ADMIN_USER" ] || [ "$2" = "$CMO_APP_USER" ]; then
        echo "cache-me-outside: $1 must differ from the admin and app users" >&2
        exit 1
    fi
    if [ "$3" = "$CMO_ADMIN_PASSWORD" ] || [ "$3" = "$CMO_APP_PASSWORD" ]; then
        echo "cache-me-outside: $1 password must differ from the admin and app passwords" >&2
        exit 1
    fi
}

repl_user="$CMO_ADMIN_USER"
repl_pass="$CMO_ADMIN_PASSWORD"
if [ -n "${CMO_REPL_USER:-}" ]; then
    require_user "$CMO_REPL_USER" CMO_REPL_USER
    require_password "${CMO_REPL_PASSWORD:?Set CMO_REPL_PASSWORD with CMO_REPL_USER}" CMO_REPL_PASSWORD
    distinct_account CMO_REPL_USER "$CMO_REPL_USER" "$CMO_REPL_PASSWORD"
    repl_user="$CMO_REPL_USER"
    repl_pass="$CMO_REPL_PASSWORD"
fi

sentinel_user="$CMO_ADMIN_USER"
sentinel_pass="$CMO_ADMIN_PASSWORD"
if [ -n "${CMO_SENTINEL_USER:-}" ]; then
    require_user "$CMO_SENTINEL_USER" CMO_SENTINEL_USER
    require_password "${CMO_SENTINEL_PASSWORD:?Set CMO_SENTINEL_PASSWORD with CMO_SENTINEL_USER}" CMO_SENTINEL_PASSWORD
    distinct_account CMO_SENTINEL_USER "$CMO_SENTINEL_USER" "$CMO_SENTINEL_PASSWORD"
    sentinel_user="$CMO_SENTINEL_USER"
    sentinel_pass="$CMO_SENTINEL_PASSWORD"
fi

cluster_user=""
cluster_pass=""
if [ -n "${CMO_CLUSTER_USER:-}" ]; then
    require_user "$CMO_CLUSTER_USER" CMO_CLUSTER_USER
    require_password "${CMO_CLUSTER_PASSWORD:?Set CMO_CLUSTER_PASSWORD with CMO_CLUSTER_USER}" CMO_CLUSTER_PASSWORD
    distinct_account CMO_CLUSTER_USER "$CMO_CLUSTER_USER" "$CMO_CLUSTER_PASSWORD"
    cluster_user="$CMO_CLUSTER_USER"
    cluster_pass="$CMO_CLUSTER_PASSWORD"
fi

if [ -n "${CMO_REPL_USER:-}" ] && [ -n "${CMO_SENTINEL_USER:-}" ] && [ "$CMO_REPL_USER" = "$CMO_SENTINEL_USER" ]; then
    echo "cache-me-outside: CMO_REPL_USER and CMO_SENTINEL_USER must differ" >&2
    exit 1
fi
if [ -n "${CMO_REPL_USER:-}" ] && [ -n "$cluster_user" ] && [ "$CMO_REPL_USER" = "$cluster_user" ]; then
    echo "cache-me-outside: CMO_REPL_USER and CMO_CLUSTER_USER must differ" >&2
    exit 1
fi
if [ -n "${CMO_SENTINEL_USER:-}" ] && [ -n "$cluster_user" ] && [ "$CMO_SENTINEL_USER" = "$cluster_user" ]; then
    echo "cache-me-outside: CMO_SENTINEL_USER and CMO_CLUSTER_USER must differ" >&2
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
mkdir -p "$CMO_DATA_DIR" "$CMO_RUNTIME_DIR"
acl_file="${CMO_RUNTIME_DIR}/cmo-users.acl"
{
    printf '%s\n' "user default reset"
    printf '%s\n' "user ${CMO_ADMIN_USER} on >${CMO_ADMIN_PASSWORD} ~* &* +@all"
    printf '%s\n' "user ${CMO_APP_USER} on >${CMO_APP_PASSWORD} ~* &* ${app_acl}"
    if [ -n "${CMO_REPL_USER:-}" ] && [ "$CMO_ROLE" != "sentinel" ]; then
        # The replica authenticates to the primary with these commands only.
        printf '%s\n' "user ${repl_user} on >${repl_pass} ~* &* +psync +sync +replconf +ping +client|setname +info"
    fi
    if [ -n "${CMO_SENTINEL_USER:-}" ]; then
        if [ "$CMO_ROLE" = "sentinel" ]; then
            # Other Sentinels authenticate with this user for hello and quorum checks.
            printf '%s\n' "user ${sentinel_user} on >${sentinel_pass} ~* &* +@all -@dangerous -@admin +ping +subscribe +unsubscribe +psubscribe +punsubscribe +publish +sentinel|is-master-down-by-addr +sentinel|get-master-addr-by-name +sentinel|get-primary-addr-by-name +sentinel|sentinels +sentinel|replicas +sentinel|slaves +sentinel|masters +sentinel|primaries"
        else
            # Sentinel's auth-user on a data node. Failover sends REPLICAOF, CONFIG REWRITE,
            # and CLIENT KILL. Sentinels also PUBLISH and SUBSCRIBE the hello channel here;
            # without that they never see each other and quorum cannot be reached.
            printf '%s\n' "user ${sentinel_user} on >${sentinel_pass} ~* &* +ping +info +replconf +multi +exec +role +replicaof +slaveof +failover +config|rewrite +config|get +config|set +client|setname +client|kill +subscribe +unsubscribe +psubscribe +punsubscribe +publish"
        fi
    fi
    if [ -n "$cluster_user" ] && [ "$CMO_ROLE" != "sentinel" ]; then
        # Tooling user for valkey-cli --cluster. The cluster bus is not this account.
        # MIGRATE SELECTs, then the source connects to the destination as this
        # same user (AUTH2) and runs RESTORE / RESTORE-ASKING. Adding a primary
        # also copies functions (FUNCTION DUMP, LIST, and RESTORE).
        printf '%s\n' "user ${cluster_user} on >${cluster_pass} ~* &* +select +restore +restore-asking +migrate +cluster +asking +readonly +readwrite +ping +info +function|dump +function|list +function|restore +config|get"
    fi
} > "$acl_file"
chmod 600 "$acl_file"

# Hostnames are opt-in. The default stores IPs so a dead container's name
# cannot block Sentinel in DNS. A lookup longer than about 2s trips TILT.
sentinel_hostnames="no"
case "${CMO_SENTINEL_ANNOUNCE_HOSTNAMES:-no}" in
    yes) sentinel_hostnames="yes" ;;
    no) sentinel_hostnames="no" ;;
    *)
        echo "cache-me-outside: CMO_SENTINEL_ANNOUNCE_HOSTNAMES must be yes or no" >&2
        exit 1
        ;;
esac

# Address Docker assigned to this container, from /etc/hosts. Empty if unknown.
cmo_container_ip() {
    host_name=""
    if [ -r /etc/hostname ]; then
        host_name="$(tr -d '[:space:]' < /etc/hostname)"
    fi
    if [ -z "$host_name" ]; then
        host_name="$(hostname 2>/dev/null || true)"
    fi
    case "$host_name" in
        "" | localhost | 127.0.0.1) return 0 ;;
    esac
    if ! command -v getent >/dev/null 2>&1; then
        return 0
    fi
    getent hosts "$host_name" | awk '$1 != "127.0.0.1" && $1 != "::1" { print $1; exit }'
}

if [ "$CMO_ROLE" = "sentinel" ]; then
    : "${CMO_PRIMARY_HOST:?Set CMO_PRIMARY_HOST for a sentinel}"
    : "${CMO_PRIMARY_PORT:=6379}"
    umask 077
    # glibc waits 5s per attempt by default. That stall is enough to enter TILT
    # and hold a failover for tens of seconds. One short attempt is enough.
    if [ -z "${RES_OPTIONS:-}" ]; then
        export RES_OPTIONS="timeout:1 attempts:1"
    fi
    # Monitor the address resolved at start. A killed container drops out of
    # Docker DNS, and Sentinel will not fail over while it is still trying to
    # resolve that name. The default is to keep the IP and not resolve again.
    if command -v getent >/dev/null 2>&1; then
        resolved=""
        try=0
        while [ "$try" -lt 30 ]; do
            resolved="$(getent hosts "$CMO_PRIMARY_HOST" | awk '$1 != "127.0.0.1" && $1 != "::1" { print $1; exit }')"
            if [ -n "$resolved" ]; then
                CMO_PRIMARY_HOST="$resolved"
                break
            fi
            try=$((try + 1))
            sleep 1
        done
    fi
    case "$CMO_PRIMARY_HOST" in
        [0-9]*.[0-9]*.[0-9]*.[0-9]*) ;;
        *)
            echo "cache-me-outside: could not resolve CMO_PRIMARY_HOST to an address; Sentinel will monitor ${CMO_PRIMARY_HOST}" >&2
            ;;
    esac
    # Sentinel rewrites this file as it learns replicas. Overwriting it on
    # every start drops that list until the next discovery pass, and a
    # failover in that window fails with "no good replica". A later start
    # refreshes the monitored primary address and the auth lines, and leaves
    # the learned replica lines in place. Auth is rewritten so a password
    # change in the environment replaces the secret stored on the volume.
    sentinel_conf="${CMO_RUNTIME_DIR}/cmo-sentinel.conf"
    if [ -s "$sentinel_conf" ]; then
        awk -v name="$CMO_SENTINEL_MASTER" -v ip="$CMO_PRIMARY_HOST" \
            -v user="$sentinel_user" -v pass="$sentinel_pass" \
            -v down="$CMO_SENTINEL_DOWN_AFTER_MS" -v failover="$CMO_SENTINEL_FAILOVER_TIMEOUT" \
            -v hostnames="$sentinel_hostnames" -v acl="$acl_file" '
            $1 == "sentinel" && $2 == "monitor" && $3 == name { $4 = ip }
            $1 == "aclfile" { print "aclfile " acl; seen_acl = 1; next }
            $1 == "sentinel" && $2 == "auth-user" && $3 == name {
                print "sentinel auth-user " name " " user
                seen_auth_user = 1
                next
            }
            $1 == "sentinel" && $2 == "auth-pass" && $3 == name {
                print "sentinel auth-pass " name " " pass
                seen_auth_pass = 1
                next
            }
            $1 == "sentinel" && $2 == "down-after-milliseconds" && $3 == name {
                print "sentinel down-after-milliseconds " name " " down
                seen_down = 1
                next
            }
            $1 == "sentinel" && $2 == "failover-timeout" && $3 == name {
                print "sentinel failover-timeout " name " " failover
                seen_fail = 1
                next
            }
            $1 == "sentinel" && $2 == "resolve-hostnames" {
                print "sentinel resolve-hostnames " hostnames
                seen_resolve = 1
                next
            }
            $1 == "sentinel" && $2 == "announce-hostnames" {
                print "sentinel announce-hostnames " hostnames
                seen_announce = 1
                next
            }
            $1 == "sentinel" && $2 == "sentinel-user" {
                print "sentinel sentinel-user " user
                seen_suser = 1
                next
            }
            $1 == "sentinel" && $2 == "sentinel-pass" {
                print "sentinel sentinel-pass " pass
                seen_spass = 1
                next
            }
            { print }
            END {
                if (!seen_acl) print "aclfile " acl
                if (!seen_auth_user) print "sentinel auth-user " name " " user
                if (!seen_auth_pass) print "sentinel auth-pass " name " " pass
                if (!seen_down) print "sentinel down-after-milliseconds " name " " down
                if (!seen_fail) print "sentinel failover-timeout " name " " failover
                if (!seen_resolve) print "sentinel resolve-hostnames " hostnames
                if (!seen_announce) print "sentinel announce-hostnames " hostnames
                if (!seen_suser) print "sentinel sentinel-user " user
                if (!seen_spass) print "sentinel sentinel-pass " pass
            }
        ' "$sentinel_conf" > "${sentinel_conf}.new"
        mv "${sentinel_conf}.new" "$sentinel_conf"
        chmod 600 "$sentinel_conf"
    else
        {
            printf '%s\n' "bind ${CMO_CONTAINER_BIND}"
            printf '%s\n' "port ${CMO_PORT}"
            printf '%s\n' "protected-mode yes"
            printf '%s\n' "daemonize no"
            printf '%s\n' "supervised no"
            printf '%s\n' "logfile \"\""
            printf '%s\n' "dir ${CMO_RUNTIME_DIR}"
            printf '%s\n' "aclfile ${acl_file}"
            printf '%s\n' "sentinel monitor ${CMO_SENTINEL_MASTER} ${CMO_PRIMARY_HOST} ${CMO_PRIMARY_PORT} ${CMO_SENTINEL_QUORUM}"
            printf '%s\n' "sentinel auth-user ${CMO_SENTINEL_MASTER} ${sentinel_user}"
            printf '%s\n' "sentinel auth-pass ${CMO_SENTINEL_MASTER} ${sentinel_pass}"
            printf '%s\n' "sentinel down-after-milliseconds ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_DOWN_AFTER_MS}"
            printf '%s\n' "sentinel failover-timeout ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_FAILOVER_TIMEOUT}"
            printf '%s\n' "sentinel parallel-syncs ${CMO_SENTINEL_MASTER} ${CMO_SENTINEL_PARALLEL_SYNCS}"
            printf '%s\n' "sentinel resolve-hostnames ${sentinel_hostnames}"
            printf '%s\n' "sentinel announce-hostnames ${sentinel_hostnames}"
            printf '%s\n' "sentinel sentinel-user ${sentinel_user}"
            printf '%s\n' "sentinel sentinel-pass ${sentinel_pass}"
            if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
                printf '%s\n' "sentinel announce-ip ${CMO_ANNOUNCE_IP}"
                printf '%s\n' "sentinel announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
            fi
        } > "$sentinel_conf"
        chmod 600 "$sentinel_conf"
    fi
    exec valkey-sentinel "$sentinel_conf" "$@"
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
# valkey.conf says `dir /data`. That path exists in the image. On a VM the
# data directory is /var/lib/cache-me-outside, and Valkey rejects the include
# before a later `dir` line can override it. Rewrite those two paths first.
sed \
    -e "s|^dir /data\$|dir ${CMO_DATA_DIR}|" \
    -e "s|^aclfile /tmp/cmo-users.acl\$|aclfile ${acl_file}|" \
    /etc/cache-me-outside/valkey.conf > "${CMO_RUNTIME_DIR}/valkey.included.conf"
{
    printf '%s\n' "include ${CMO_RUNTIME_DIR}/valkey.included.conf"
    printf '%s\n' "dir ${CMO_DATA_DIR}"
    printf '%s\n' "aclfile ${acl_file}"
    printf '%s\n' "bind ${CMO_CONTAINER_BIND}"
    printf '%s\n' "port ${CMO_PORT}"
    printf '%s\n' "maxmemory ${CMO_MAXMEMORY}"
    printf '%s\n' "maxmemory-policy ${CMO_MAXMEMORY_POLICY}"
    printf '%s\n' "io-threads ${CMO_IO_THREADS}"
    if [ "$CMO_CLUSTER_ENABLED" = "yes" ] || [ -n "$replica_host" ]; then
        # Replicas authenticate as CMO_REPL_USER when that account is set, otherwise admin.
        # The app user cannot SYNC/PSYNC.
        printf '%s\n' "masteruser ${repl_user}"
        printf '%s\n' "masterauth ${repl_pass}"
    fi
    if [ -n "$replica_host" ]; then
        printf '%s\n' "replicaof ${replica_host} ${replica_port}"
        if [ -n "${CMO_ANNOUNCE_IP:-}" ]; then
            printf '%s\n' "replica-announce-ip ${CMO_ANNOUNCE_IP}"
            printf '%s\n' "replica-announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
        elif [ "$sentinel_hostnames" = "yes" ]; then
            announced="$(hostname 2>/dev/null || true)"
            case "$announced" in
                "" | localhost | 127.0.0.1) ;;
                *)
                    printf '%s\n' "replica-announce-ip ${announced}"
                    printf '%s\n' "replica-announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
                    ;;
            esac
        else
            # Announce the address Docker assigned. Sentinel stores that IP, so
            # failover does not wait on DNS after this container's name is gone.
            announced="$(cmo_container_ip || true)"
            case "$announced" in
                "") ;;
                *)
                    printf '%s\n' "replica-announce-ip ${announced}"
                    printf '%s\n' "replica-announce-port ${CMO_ANNOUNCE_PORT:-${CMO_PORT}}"
                    ;;
            esac
        fi
    fi
    if [ "$CMO_CLUSTER_ENABLED" = "yes" ]; then
        printf '%s\n' "cluster-enabled yes"
        printf '%s\n' "cluster-config-file ${CMO_DATA_DIR}/nodes.conf"
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
} > "${CMO_RUNTIME_DIR}/cmo-runtime.conf"
chmod 600 "${CMO_RUNTIME_DIR}/cmo-runtime.conf"

exec valkey-server "${CMO_RUNTIME_DIR}/cmo-runtime.conf" "$@"
