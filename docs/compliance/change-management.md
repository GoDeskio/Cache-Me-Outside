# Change management

A change to a running cache is a reviewed pull request against `unstable`, plus a deploy of a build from that commit. Direct pushes to `unstable` are not the path.

What a review is expected to look at:

- The diff does what the description says.
- Tests cover the behavior that changed. Engine changes run the Valkey suite.
- Secrets, real inventories, and customer data are not in the diff.
- A config default that affects every server is called out in the description.

Emergency changes still get a pull request, opened before the deploy or immediately after if the process was already down. The incident write-up links to that pull request.

The repo history is the change log. This document does not add a second tracker.
