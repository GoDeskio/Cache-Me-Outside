# SOC 2 readiness pack

These documents are drafts for a future SOC 2 Type I review of Cache Me Outside. They are not a certification, not an auditor's report, and not evidence that a control has been tested by a third party.

The pack covers the Trust Services Criteria that a cache service usually has to speak to: security (the common criteria), plus availability because the service publishes uptime tiers. Confidentiality and privacy are noted only where the service actually holds customer data.

## Documents

| Document | What it is |
|---|---|
| [control-matrix.md](control-matrix.md) | Criteria, the control we intend, and whether it is technical or still manual |
| [access-control.md](access-control.md) | Who can reach production and the console |
| [change-management.md](change-management.md) | How code reaches a running cache |
| [incident-response.md](incident-response.md) | How an incident is opened, contained, and written up |
| [vendor-management.md](vendor-management.md) | Subprocessors and what they are allowed to see |
| [availability.md](availability.md) | How the 99.9% and 99.95% tiers map to topology |
| [evidence-index.md](evidence-index.md) | Where an auditor would look, and what is not collected yet |
| [risk-assessment.md](risk-assessment.md) | The risks we know about and the open ones |

Owners are blank on purpose. A named owner is an appointment, not something this pack invents.
