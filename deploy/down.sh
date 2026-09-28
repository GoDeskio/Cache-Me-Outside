#!/usr/bin/env bash
# Stop the Cache-Me-Outside project selected by CMO_PROJECT.
#
# Volumes are kept unless --volumes is passed. Deleting volumes for the
# default project (cache-me-outside, or CMO_PRODUCTION_PROJECT) also requires
# --i-know or an explicit CMO_PROJECT. A bare ./down.sh therefore cannot wipe
# the production data volume.
#
#   ./down.sh                  stop this project, keep volumes
#   ./down.sh --volumes        also delete this project's volumes
#   ./down.sh --remove-orphans also pass --remove-orphans to compose
#   ./down.sh --volumes --i-know
#                              delete volumes even when CMO_PROJECT was defaulted
set -euo pipefail

cd "$(dirname "$0")"

remove_volumes=0
remove_orphans=0
i_know=0
for arg in "$@"; do
    case "$arg" in
        --volumes) remove_volumes=1 ;;
        --remove-orphans) remove_orphans=1 ;;
        --i-know) i_know=1 ;;
        *)
            echo "Unknown argument: ${arg}" >&2
            exit 1
            ;;
    esac
done

# cmo_apply_names fills in cache-me-outside when this is unset. Remember
# whether the caller named a project before that default is applied.
project_explicit=0
if [[ -n "${CMO_PROJECT:-}" ]]; then
    project_explicit=1
fi

# shellcheck disable=SC1091
source ./lib.sh
cmo_apply_names

if [[ "$remove_volumes" -eq 1 && "$i_know" -eq 0 && "$project_explicit" -eq 0 ]]; then
    if [[ "$CMO_PROJECT" == "$CMO_PRODUCTION_PROJECT" || "$CMO_PROJECT" == "cache-me-outside" ]]; then
        echo "Refusing to delete volumes for the default project ${CMO_PROJECT}." >&2
        echo "Pass --volumes with --i-know, or set CMO_PROJECT to the project whose data should be deleted." >&2
        exit 1
    fi
fi

compose_down() {
    local file="$1"
    local -a args=(down)
    if [[ "$remove_volumes" -eq 1 ]]; then
        args+=(-v)
    fi
    if [[ "$remove_orphans" -eq 1 ]]; then
        args+=(--remove-orphans)
    fi
    if [[ -f "$file" ]]; then
        cmo_dc -f "$file" "${args[@]}" || true
    fi
}

compose_down "$(cmo_deploy_dir)/docker-compose.yml"
compose_down "$(cmo_compose_file)"
compose_down "$(cmo_deploy_dir)/docker-compose.node.yml"

if [[ "$remove_volumes" -eq 1 ]]; then
    # Volumes are global on the Docker host. Only remove names for this prefix.
    prefix="$CMO_NAME_PREFIX"
    while IFS= read -r volume; do
        [[ -z "$volume" ]] && continue
        docker volume rm "$volume" >/dev/null 2>&1 || true
    done < <(docker volume ls -q | grep -E "^${prefix}(-data|-primary-data|-replica-[0-9]+-data|-sentinel-[0-9]+-data|-cluster-[0-9]+-data|-node-data)$" || true)
fi

rm -rf "$(cmo_generated_dir)"
if [[ "$remove_volumes" -eq 1 ]]; then
    echo "stopped ${CMO_PROJECT} and removed its volumes"
else
    echo "stopped ${CMO_PROJECT} (volumes kept)"
fi
