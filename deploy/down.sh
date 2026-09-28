#!/usr/bin/env bash
# Stop every Cache-Me-Outside topology this directory can start, and delete its volumes.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh

compose_down() {
    local file="$1"
    if [[ -f "$file" ]]; then
        cmo_dc -f "$file" down -v --remove-orphans || true
    fi
}

compose_down docker-compose.yml
compose_down .generated/compose.yml
compose_down docker-compose.node.yml

# Volumes survive if the generated compose file was already removed.
while IFS= read -r volume; do
    [[ -z "$volume" ]] && continue
    docker volume rm "$volume" >/dev/null 2>&1 || true
done < <(docker volume ls -q | grep -E '^(cache-me-outside-data|cmo-primary-data|cmo-replica-[0-9]+-data|cmo-cluster-[0-9]+-data|cmo-node-data)$' || true)

rm -rf .generated
echo "stopped"
