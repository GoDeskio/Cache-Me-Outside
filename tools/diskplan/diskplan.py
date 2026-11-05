#!/usr/bin/env python3
"""Disk-first plan backed by Apache Kvrocks (plan item 25).

For datasets bigger than RAM we offer a plan that runs Apache Kvrocks
(Apache-2.0, RocksDB on NVMe, Redis protocol) instead of Valkey. We use the
upstream image as-is; this module renders its config from a plan size and
lists the commands that differ so the proxy can reject them clearly.
"""
import re

PLANS = {  # disk GB -> (rocksdb block cache MB, worker threads)
    50: (512, 4), 200: (2048, 8), 1000: (8192, 16),
}
# Valkey features Kvrocks does not support (proxy answers with a clear error).
UNSUPPORTED = {"MODULE", "FUNCTION", "FT.CREATE", "FT.SEARCH", "JSON.SET", "BF.ADD", "WAITAOF", "SWAPDB"}


def config(disk_gb, password_file="/run/secrets/kvrocks.conf", tls=True):
    if disk_gb not in PLANS:
        raise ValueError("plan sizes: %s" % sorted(PLANS))
    cache, workers = PLANS[disk_gb]
    lines = ["bind 0.0.0.0", "dir /data", "workers %d" % workers,
             "rocksdb.block_cache_size %d" % cache,
             "rocksdb.compression zstd",
             "max-backup-to-keep 1",
             "include %s" % password_file]  # holds `requirepass`; never inline secrets
    lines += ["port 0", "tls-port 6380", "tls-cert-file /tls/server.crt",
              "tls-key-file /tls/server.key", "tls-ca-cert-file /tls/ca.crt"] if tls else ["port 6379"]
    return "\n".join(lines) + "\n"


def check_command(argv):
    """Return None if allowed on the disk plan, else an error string for the client."""
    name = argv[0].upper() if argv else ""
    if name in UNSUPPORTED or re.match(r"^(FT|JSON|BF|CF|TS)\.", name):
        return "ERR %s is not available on the disk plan" % name
    return None
