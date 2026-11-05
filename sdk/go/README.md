# Cache Me Outside Go SDK

This package uses only the Go standard library.

- `ParseURL` reads `redis`, `rediss`, `valkey` and `valkeys` URLs.
- `NewTenant(client, "acme")` adds the tenant prefix to keys for any client that implements `KV`, such as a small adapter over valkey-glide's Go client.
- Run the tests with `go test ./...`.
- Status: not yet tested against a live server. A ready-made Glide adapter is a follow-up.
