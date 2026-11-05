# Warm restart

A clean shutdown can write a checkpoint that the next process loads when it would otherwise start empty. RDB saves and AOF stay the durability path. The checkpoint is used only when those files are not loaded.

```
cmo-warm-enabled yes
cmo-warm-file /var/lib/cache-me-outside/warm.rdb
```

`cmo-warm-file` has to be a different path from `dbfilename`. Shutdown writes the snapshot, then a `cmo-warm-file.hdr` checksum. Startup loads the snapshot only when that header matches. A torn write does not match, so the process starts cold instead of reading a partial file.

`save ""` and `appendonly no` still come back with the previous cache after `SHUTDOWN` or SIGTERM. A crash keeps the last checkpoint that finished, which can be older than the last write.
