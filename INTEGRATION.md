# Adopt Cache Me Outside

The integration directory is the whole package: a Python client, a browser/Node client, a loopback sidecar, and an updater. Version `1.0.0` is recorded in `integration/manifest.json`. Copy that directory into a GoDesk app, or install a `cmo-integration-vX.Y.Z` release. No token or password belongs in the repository.

## Python

```python
import os
from cache_me_outside import Client

client = Client(os.environ["CMO_API"], os.environ["CMO_ADMIN_TOKEN"])
print(client.list_databases())
```

## Browser or Node

```html
<script src="integration/cache-me-outside.js"></script>
<script>
  const cache = CacheMeOutside.attach({
    api: location.origin,
    token: sessionToken
  });
  const rows = await cache.listDatabases();
</script>
```

`sessionToken` comes from your own sign-in. The script does not contain one.

## Sidecar

```bash
CMO_API=http://127.0.0.1:8088 CMO_ADMIN_TOKEN="$CMO_ADMIN_TOKEN" \
  python3 integration/sidecar.py
```

The app then calls `GET http://127.0.0.1:8099/health`. The sidecar binds to loopback only. Cache get and set also need `CMO_URL` and `CMO_PREFIX`; a key outside that prefix is refused before a connection opens.

## Updates

```bash
python3 integration/updater.py --check
python3 integration/updater.py --apply
```

`--apply` reads GitHub releases named `cmo-integration-vX.Y.Z`, downloads `cache-me-outside-integration.tar.gz` and `SHA256SUMS`, and writes files only when the checksum matches. It refuses other hosts, symlinks, and paths that leave the integration directory. When no release is published yet, `--check` reports that and leaves the files alone.
