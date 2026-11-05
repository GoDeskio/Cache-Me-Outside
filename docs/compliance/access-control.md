# Access control

## Console

Sign-in is self-hosted Authentik over OIDC. Authentik is the only identity provider for the console. Group names map to the roles shipped with the console RBAC work:

| Authentik group | Role | Can |
|---|---|---|
| cache-viewers | viewer | Read metrics, config, and the audit log |
| cache-developers | developer | Read and write data, rotate their own keys |
| cache-admins | admin | Create and delete databases, manage keys and members |
| (none) | owner | Billing, delete the team, grant another owner |

No group maps to owner. An owner is added by an existing owner. That matches the rule that an IdP group cannot grant the top role.

People who leave have their Authentik account disabled and their console membership removed on the same day. The record of that removal is the evidence for CC6.2. The repo does not store that record.

## Data plane

Applications use per-app ACL users, not the admin user. Admin passwords are not committed. The example files use placeholders and the server refuses them.

Production listeners do not bind to a public address unless a ticket says why.

## FIPS

`make BUILD_FIPS=yes` is an optional build. The default binary is not a FIPS build. `INFO server` shows `cmo_fips_build`. Turning the flag on does not by itself supply a FIPS-validated crypto module. The operator still has to link one.
