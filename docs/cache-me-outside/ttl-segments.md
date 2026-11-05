# TTL-grouped storage

Keys that expire in the same time bucket can be dropped together. The bucket width is `cmo-ttl-segment-ms` (default 1000). A key's expiry is rounded up to that width. When the bucket ends, every key still in it is deleted in one pass.

```
cmo-ttl-segments yes
cmo-ttl-segment-ms 1000
```

This is off by default. Reads still honor the exact TTL, so a key fetched before the bucket ends expires at the time the client asked for. The segment pass is what removes keys nobody reads, without sampling the keyspace one key at a time.

`INFO cmo_ttl` reports how many keys are tracked and how many the reaper has deleted.

The grouping is original to this tree. It is not Pelikan's segment layout.
