# API keys on Sentinel and cluster

`deploy/api-key.sh` writes the records and applies the ACL users on every data container in the compose project. Sentinels are skipped. A key therefore works on any node and still works after failover.

- Set `CMO_KEYS_CONTAINERS` to override the node list.
- After adding a node, run `api-key.sh sync`.
- If any node fails, the command exits non-zero and says to rerun it. Rerunning is safe.

The main design is in api-keys-design.md (PR #6).
