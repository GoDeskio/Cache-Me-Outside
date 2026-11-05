# Evidence index

An auditor would ask for the artifacts below. "Present" means the repo or the running system can produce it today. "Gap" means we would have to start collecting it.

| Ask | Where it would come from | State |
|---|---|---|
| System description | README and `docs/cache-me-outside/` | Present |
| Access list for the console | Authentik users and group membership | Gap until Authentik is deployed |
| Access list for the data plane | `ACL LIST` on each node | Present once a node is up |
| Change list | Git history of `unstable` and the deploy record | Git is present. Deploy record is a gap |
| Incident log | The notes described in incident-response.md | Gap. No incidents filed under this process |
| Uptime tier per database | The database record's tier field, 99.9 or 99.95 | Gap until the console stores it |
| Backup restore test | A dated note that a backup was restored and checked | Gap |
| Vendor list | [vendor-management.md](vendor-management.md) | Present |
| Risk assessment | [risk-assessment.md](risk-assessment.md) | Draft only |

Do not backfill this table with invented dates or sample evidence.
