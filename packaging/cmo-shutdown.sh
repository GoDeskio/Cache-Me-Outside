#!/bin/sh
# Ask the local server to exit. Data nodes rewrite the AOF/RDB first.
# Sentinel has no dataset, so it shuts down without SAVE.
set -eu

port="${CMO_PORT:-6379}"
user="${CMO_ADMIN_USER:?CMO_ADMIN_USER is required}"
pass="${CMO_ADMIN_PASSWORD:?CMO_ADMIN_PASSWORD is required}"

if [ "${CMO_ROLE:-standalone}" = "sentinel" ]; then
    exec valkey-cli -h 127.0.0.1 -p "$port" \
        --user "$user" -a "$pass" --no-auth-warning SHUTDOWN NOSAVE
fi

exec valkey-cli -h 127.0.0.1 -p "$port" \
    --user "$user" -a "$pass" --no-auth-warning SHUTDOWN SAVE
