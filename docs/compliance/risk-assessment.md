# Risk assessment

Draft. It has not been reviewed on a cadence, so CC3.1 is still open.

| Risk | What happens | What we do now | Left open |
|---|---|---|---|
| A single host dies | That node's keys are unavailable until failover | Replica plus Sentinel or cluster, when the operator turned them on | A database sold at 99.9% or 99.95% with one node |
| Admin credential in git | Anyone with the repo becomes admin | Placeholders are refused at startup | A real password pasted into a commit |
| Console account without a role review | A departed person keeps access | Authentik is the front door, owner is not an IdP group | No periodic access review yet |
| Snapshot leaves the host | A copy of customer values sits in another system | Snapshots stay on the node unless an export is configured | No approved export destination |
| FIPS assumed because the flag exists | A buyer thinks the default build is FIPS | `cmo_fips_build` is `no` unless the binary was built with `BUILD_FIPS=yes` | Linking a validated module is still an operator task |
| Placeholder price shipped as a real bill | A customer is charged a made-up amount | Pricing code refuses to quote a `PLACEHOLDER` rate | Someone replaces the placeholder with a number and does not review it |

Review this list when a tier, a vendor, or the sign-in path changes. Put the date of that review here. There is no date yet.
