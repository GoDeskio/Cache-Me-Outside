#!/usr/bin/env bash
# Open or update a pull request that merges valkey-io/valkey unstable.
# Never force-pushes. Merge conflicts fail the job so a person can resolve them.
set -euo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" && "${CMO_SYNC_ALLOW_LOCAL:-}" != "1" ]]; then
    echo "Refusing to sync outside GitHub Actions. Set CMO_SYNC_ALLOW_LOCAL=1 to override." >&2
    exit 1
fi

upstream_url="${CMO_UPSTREAM_URL:-https://github.com/valkey-io/valkey.git}"
upstream_branch="${CMO_UPSTREAM_BRANCH:-unstable}"
target_branch="${CMO_TARGET_BRANCH:-unstable}"
stamp="$(date -u +%Y%m%d)"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git remote add upstream "$upstream_url" 2>/dev/null || git remote set-url upstream "$upstream_url"
git fetch upstream "$upstream_branch"
git fetch origin "$target_branch"

gh label create upstream-sync \
    --description "Automated merge from valkey-io/valkey unstable" \
    --color 1D76DB >/dev/null 2>&1 || true

existing="$(gh pr list --base "$target_branch" --state open --label upstream-sync \
    --json headRefName --jq '.[0].headRefName // ""')"

if [[ -n "$existing" ]]; then
    branch="$existing"
    git fetch origin "$branch"
    git checkout -B "$branch" "origin/${branch}"
    if ! git merge-base --is-ancestor "origin/${target_branch}" HEAD; then
        git merge --no-edit "origin/${target_branch}" \
            -m "Merge ${target_branch} into the upstream sync branch"
    fi
else
    branch="upstream-sync/${stamp}"
    git checkout -B "$branch" "origin/${target_branch}"
fi

if git merge-base --is-ancestor "upstream/${upstream_branch}" HEAD; then
    if [[ -z "$existing" ]]; then
        echo "Already up to date with ${upstream_url} ${upstream_branch}."
        exit 0
    fi
    if git diff --quiet "origin/${branch}" HEAD; then
        echo "Open sync pull request is already current."
        exit 0
    fi
else
    git merge --no-ff --no-edit "upstream/${upstream_branch}" \
        -m "Merge upstream valkey-io/valkey ${upstream_branch}"
fi

# A normal push only. Do not add --force.
git push origin "HEAD:${branch}"

if [[ -z "$existing" ]]; then
    gh pr create \
        --base "$target_branch" \
        --head "$branch" \
        --title "Sync upstream valkey-io/valkey ${upstream_branch} (${stamp})" \
        --label upstream-sync \
        --body "$(cat <<EOF
Automated merge of [\`valkey-io/valkey\`](https://github.com/valkey-io/valkey) \`${upstream_branch}\` into Cache-Me-Outside.

This workflow pushes a normal branch update and opens a pull request. It does not force-push. If the merge conflicts, the job fails and the branch is left for a manual resolution.

Review the Valkey changes before merging, especially anything under \`src/\` that touches behavior this fork depends on (\`INFO\` \`cmo_version\`, ACL, and persistence).

EOF
)"
fi

echo "Sync branch ${branch} is pushed."
