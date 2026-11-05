# DRAM + flash hybrid storage

Large string values can live in a flash log while the key, TTL, and an 8-to-12 byte locator stay in DRAM. This is a cache tier. RDB and AOF still store the real bytes, and the flash file is truncated every time the process starts.

It is off unless both of these are set:

```
cmo-hybrid-enabled yes
cmo-hybrid-file /var/lib/cache-me-outside/hybrid.dat
```

`cmo-hybrid-min-value` (default 4096, minimum 64) is the smallest string, in bytes, that spills. `cmo-hybrid-max-bytes` (default 1 GiB) caps the log. When the log is full, further values stay in DRAM.

A value spills only after the command that wrote it has been propagated and no other reference holds the object. The next read copies it back into DRAM. `INFO cmo_hybrid` reports spill and promotion counts.

The layout is original to this tree. It is not CacheLib's Navy or BigHash format.
