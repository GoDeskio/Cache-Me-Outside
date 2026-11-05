# Design: scoped, expiring API keys that survive restarts (plan item 63)

## Problem
`docker-entrypoint.sh` rebuilds `cmo-users.acl` from the environment on every
start and writes it to the runtime directory (`/tmp`). A user added at runtime
with `ACL SETUSER` is lost on restart, and `ACL SAVE` would write to a file the
next start overwrites. Keys therefore need their own store.

## Decisions
1. **Store on the data volume:** `${CMO_DATA_DIR}/cmo-keys` (mode 0600, owner
   `valkey`). It survives restarts and container replacement, and travels with
   the volume. It is not the ACL file and is never loaded by the server directly.
2. **Structured records, not ACL text.** One key per line:
   `key-<id> <expires_epoch|0> <scope> <prefix> <sha256-hex>`.
   The entrypoint renders each record into an ACL line from a fixed template.
   A tampered or malformed line is skipped with a warning, so the store can never
   grant rules outside the templates (no `+@admin`, no `~*` unless the prefix is
   empty by choice).
3. **No plaintext secrets at rest.** The record holds SHA-256 of the secret; the
   ACL line uses `#<hash>`. The secret is printed once at creation.
4. **Scopes** (fixed templates):
   - `ro`: `+@read +ping +auth +hello -@dangerous -@admin`
   - `rw`: `+@read +@write +ping +auth +hello -@dangerous -@admin`
   Both use `resetchannels`, `resetkeys ~<prefix>*` (prefix limited to
   `[A-Za-z0-9:_.-]`, max 64 chars).
5. **Expiry.** Expired records are not rendered at start. `api-key.sh sweep`
   (cron) deletes expired users live and removes their records. `0` = no expiry.
6. **One renderer.** The host tool never builds ACL text itself. It asks the
   container: `docker-entrypoint.sh --render-keys` prints the rendered lines, and
   the tool applies them with `ACL SETUSER`, so start-up and live state match.
7. **Names.** Key users are always `key-<12 hex>`, so they cannot collide with
   or replace admin, app, replication, sentinel or cluster users.
8. **Commands:** `api-key.sh create --scope ro|rw [--prefix P] [--ttl-days N]`,
   `list`, `revoke ID`, `sweep`. All run through the admin user.

## Out of scope
Cluster/Sentinel fan-out (keys are applied to the standalone node first; cluster
needs the same store on each node and a loop over members, next PR), and the
console UI (item 61).
