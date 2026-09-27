#!/bin/sh
# Generate the ACL file from the environment, then start valkey-server.
# Passwords are never written into the image or the data volume.
set -eu

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
cat > /tmp/cmo-users.acl <<EOF
user default reset
user ${CMO_ADMIN_USER} on >${CMO_ADMIN_PASSWORD} ~* &* +@all
user ${CMO_APP_USER} on >${CMO_APP_PASSWORD} ~* &* +@all -@dangerous -@admin -flushall -flushdb -debug -config -keys -shutdown -module -acl -replicaof -slaveof -migrate -restore -sort -failover -bgsave -bgrewriteaof -save -monitor -sync -psync
EOF
chmod 600 /tmp/cmo-users.acl

exec valkey-server /etc/cache-me-outside/valkey.conf \
    --bind "$CMO_CONTAINER_BIND" \
    --port "$CMO_PORT" \
    --maxmemory "$CMO_MAXMEMORY" \
    --maxmemory-policy "$CMO_MAXMEMORY_POLICY" \
    "$@"
