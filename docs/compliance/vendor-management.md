# Vendor management

A vendor is in scope when it can see customer key names, values, or the admin credentials of a cache. Hosting the process on our own machines does not create a subprocessor. Sending logs, snapshots, or console traffic somewhere else does.

| Vendor | What they would see | Decision |
|---|---|---|
| Authentik (self-hosted) | Console account emails and group names | In use. Runs on our hosts. No customer cache values |
| Object storage for snapshots | Snapshot bytes, if that export is turned on | Not turned on by this pack |
| Error and metric sinks | Host metrics. Values must stay out of the labels | Not selected |

Before a new vendor is given production data, write down what it receives, where it runs, and who approves it. A row in this file is that record. Do not add a row for a vendor we have not actually chosen.

Authentik is self-hosted. Its availability is ours. It is not a third-party identity service.
