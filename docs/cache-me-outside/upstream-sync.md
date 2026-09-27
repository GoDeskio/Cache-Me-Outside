# Upstream sync

Cache-Me-Outside tracks `valkey-io/valkey` branch `unstable`. We do not commit directly on top of a force-pushed history.

`.github/workflows/upstream-sync.yml` runs every Monday at 06:00 UTC and can be started by hand (`workflow_dispatch`). It:

1. Fetches `https://github.com/valkey-io/valkey.git` `unstable`.
2. Creates `upstream-sync/YYYYMMDD` from our `unstable`, or checks out the branch of an open pull request labeled `upstream-sync`.
3. Merges upstream with a normal merge commit.
4. Pushes that branch with a regular `git push` (no `--force`).
5. Opens a pull request into `unstable` if one is not already open.

If our `unstable` is already even with upstream, the job exits without opening a pull request.

If the merge conflicts, the job fails. Resolve the conflicts on that branch and push again. Do not force-push and do not discard the Cache-Me-Outside files (`src/cmo_version.h`, the `cmo_version` lines in `src/server.c`, `deploy/`, `docs/cache-me-outside/`, `NOTICE`, and the two workflows).

GitHub does not run workflows on pull requests that `GITHUB_TOKEN` opens. After the sync pull request appears, open it once or push an empty commit from a user account if you need the Cache-Me-Outside CI workflow to run on it.

The upstream Valkey workflows under `.github/workflows/` still exist so rebases stay small. The workflow that should stay green on our changes is `Cache-Me-Outside` (`.github/workflows/cmo-ci.yml`): it builds the server, runs a short Valkey test subset, builds the Docker image, and runs the smoke test.
