# terraform-provider-cmo

Terraform provider for Cache Me Outside API keys (plan: Terraform provider).
It is written from scratch on HashiCorp's terraform-plugin-framework and uses a small stdlib RESP client.

## Resource: `cmo_api_key`

| Argument | Notes |
|---|---|
| `scope` | `ro` or `rw`. Uses the same ACL rules as `deploy/api-key.sh` (`-@all +@read [+@write] +ping +auth +hello -@dangerous -@admin`). |
| `prefix` | The key name prefix the key can touch, 0-64 characters from `A-Za-z0-9:_.-`. Empty means all keys. |
| `id` (computed) | `key-<12hex>`, the ACL user name. |
| `secret` (computed, sensitive) | The password. Only its SHA-256 reaches the server. **The plain value is in Terraform state, so use an encrypted backend.** |

Changing `scope` or `prefix` updates the key in place (`ACL SETUSER <id> reset ...`) and keeps the secret.
`terraform destroy` runs `ACL DELUSER` on every node.

## Provider

`nodes` (or `CMO_NODES`) must list **every data node**, not the sentinels. Keys are written to all of them,
so a key works wherever a client lands and keeps working after failover. This is the same rule as `deploy/api-key.sh`.
`password` / `CMO_ADMIN_PASSWORD`, `username` / `CMO_ADMIN_USER`, `tls` / `CMO_TLS=1`.

## Known limits

- **Restarts:** keys made by Terraform are live ACL users. They are not written to `/data/cmo-keys`, so a node restart drops them.
  On the next `terraform plan`, a key missing on some nodes raises a warning; run `terraform apply -replace=...` or change an argument to re-apply it.
  A key missing on every node is planned as a new key. Persisting through the records file needs a control-plane API, which is not built yet.
- **No expiry:** there is no `ttl_days` yet. Use `destroy` instead (`api-key.sh sweep` only handles file-backed keys).
- Not published to the Terraform Registry. That needs a GPG signing key and a registry namespace decision.

## Tests

`go test ./...` runs the unit tests. Set `CMO_TEST_ADDR=127.0.0.1:6379` to also run the live ACL test against a server with no password.
See `docs/ci/cmo-terraform.patch` for the CI step.
