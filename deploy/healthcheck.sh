#!/bin/sh
# Used by the image HEALTHCHECK. Reads the runtime environment so the
# Dockerfile does not have to escape passwords or the port.
set -eu

port="${CMO_PORT:-6379}"
valkey-cli -h 127.0.0.1 -p "$port" \
    --user "$CMO_APP_USER" \
    -a "$CMO_APP_PASSWORD" \
    --no-auth-warning \
    ping | grep -q PONG
