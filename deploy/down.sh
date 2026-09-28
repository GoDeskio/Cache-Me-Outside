#!/usr/bin/env bash
# Stop the Cache-Me-Outside project selected by CMO_PROJECT and delete its volumes.
# The default project is cache-me-outside. A test run sets cmo-test first, so
# this script does not remove a coexisting production project.
set -euo pipefail

cd "$(dirname "$0")"
# shellcheck disable=SC1091
source ./lib.sh
cmo_apply_names

compose_down() {
    local file="$1"
    if [[ -f "$file" ]]; then
        cmo_dc -f "$file" down -v --remove-orphans || true
    fi
}

compose_down "$(cmo_deploy_dir)/docker-compose.yml"
compose_down "$(cmo_compose_file)"
compose_down "$(cmo_deploy_dir)/docker-compose.node.yml"

# Volumes are global on the Docker host. Only remove names for this prefix.
prefix="$CMO_NAME_PREFIX"
while IFS= read -r volume; do
    [[ -z "$volume" ]] && continue
    docker volume rm "$volume" >/dev/null 2>&1 || true
done < <(docker volume ls -q | grep -E "^${prefix}(-data|-primary-data|-replica-[0-9]+-data|-sentinel-[0-9]+-data|-cluster-[0-9]+-data|-node-data)$" || true)

rm -rf "$(cmo_generated_dir)"
echo "stopped ${CMO_PROJECT}"
