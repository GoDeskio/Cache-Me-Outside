# Near cache (client-side caching)

`tools/nearcache/cmo_nearcache.py` keeps values a client has read in local memory.
It uses the server's RESP3 `CLIENT TRACKING`, so the server tells the client when a key it read changes.
Repeat reads of hot keys then skip the network.

- Uses default tracking mode, with one connection for both commands and invalidations.
- Invalidations that arrive while the client is idle are applied before the next `get`.
- Memory is bounded by an LRU cap (`max_keys`, default 10,000).
- A flush message from the server clears the whole local cache.
- Only `GET` is cached. Use `execute()` for other commands, uncached.
- Uses the standard library only and talks to the server directly. It does not wrap another vendor's client.

Read this helper as a reference recipe. The official SDKs (plan item 59) should offer the same behaviour.
