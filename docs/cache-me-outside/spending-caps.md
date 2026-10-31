# Spending caps (plan item 44)

The tenant proxy (`tools/proxy`) checks a `Budget` before forwarding commands.
When a tenant is over its cap, every command gets
`-ERR budget cap reached for this database` until spend drops or the cap is
raised. Connections stay open; data is not deleted.

## Hostrack-Billing side (not built yet)

Hostrack-Billing needs to expose, over https:

    GET /v1/spend/{tenant}
    Authorization: Bearer <token>        (proxy reads CMO_BILLING_TOKEN)
    200 {"spent_cents": 1234, "cap_cents": 5000}   cap_cents null = no cap

Spend is for the current billing period. It also needs a way for customers to
set the cap and an alert before the cap is hit (e.g. 80%); the CMO alerts work
(#10) can send that once billing reports the number.

## Proxy config

    "budget": {"url": "https://billing.example/api", "ttl": 30, "fail_open": true}

or `{"file": "caps.json"}` with `{"tenant": {"spent_cents": .., "cap_cents": ..}}`
for testing. `fail_open: true` (default) keeps serving if billing is down;
set false to block instead. Answers are cached for `ttl` seconds.
