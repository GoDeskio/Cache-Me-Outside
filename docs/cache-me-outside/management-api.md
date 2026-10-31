# Management API and CLI (plan item 64)

`tools/mgmt/cmo_mgmt.py` is a small REST API that creates, lists, changes and deletes databases (tenants).
`tools/mgmt/cmoctl.py` is its command-line client. The OpenAPI document is served at `GET /v1/openapi.json`.

When you create a database, the API:
- adds the database to the proxy config (`tools/proxy`) with its port (7001–7999) and limits;
- creates an ACL user on the server that can only use keys and channels named `<name>:*`, and has no admin or dangerous commands;
- returns a generated password **once**. The API does not store it.

Notes:
- **Auth:** a bearer token of 24 or more characters in `CMO_ADMIN_TOKEN`. The tool listens on 127.0.0.1 by default; put TLS in front of it before exposing it anywhere else.
- **Server connection:** set `CMO_ADMIN_USER` / `CMO_ADMIN_PASSWORD` for the server admin user.
- **Applying changes:** the proxy reads its config at start, so restart it after a change. Hot reload is a follow-up.
- **ACL persistence:** ACL changes are saved with `ACL SAVE` when the server has an aclfile. Without one, they last until the server restarts.
- **Deleting:** removes the user and the proxy entry. The database's keys are kept.

Not done yet:
- **Terraform provider:** the plan also lists one. It needs a separate Go module that calls this API; that is a follow-up.
- **Live test:** the API has not been run against a live server. The tests use a fake ACL backend.
