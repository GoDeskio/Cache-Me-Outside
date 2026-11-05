# Control matrix

Status values: `technical` means the server or the deploy tooling can show it. `manual` means a person has to do it and record it. `missing` means we do not have it yet. Nothing here is marked audited.

| ID | Criterion | Control | Status |
|---|---|---|---|
| CC1.1 | Integrity and ethics | Written conduct rules for people with production access | manual |
| CC2.2 | Communication of responsibilities | This pack plus the operator docs | manual |
| CC3.1 | Risk assessment | [risk-assessment.md](risk-assessment.md), reviewed on a set cadence | missing |
| CC5.2 | Control activities | Change review before a production deploy | manual |
| CC6.1 | Logical access | Console roles (viewer, developer, admin, owner) and per-app ACL users | technical |
| CC6.2 | Access removal | Remove the Authentik account and the ACL user the same day access ends | manual |
| CC6.3 | Role design | Least role that can do the job. Owner is not granted by an IdP group | technical |
| CC6.6 | Boundary | Private bind address, protected mode, Authentik in front of the console | technical |
| CC6.7 | Transmission | TLS when `BUILD_TLS=yes`. FIPS only when `BUILD_FIPS=yes` | technical |
| CC7.2 | Monitoring | Metrics, command log, ACL denials | technical |
| CC7.3 | Evaluation of events | Someone reads the alerts. The tool does not page a person by itself | manual |
| CC7.4 | Incident response | [incident-response.md](incident-response.md). No drill has been run | missing |
| CC8.1 | Change management | [change-management.md](change-management.md) | manual |
| A1.1 | Availability | Tiers 99.9% and 99.95%, topology in [availability.md](availability.md) | technical |
| A1.2 | Recovery | RDB/AOF and the warm-restart checkpoint. Restore is still a documented procedure | manual |
| C1.1 | Confidentiality | Customer values are not used for anything but serving that customer | manual |

HIPAA is out of scope until a customer asks for it and a BAA exists. Do not copy the SOC 2 rows into a HIPAA claim.
