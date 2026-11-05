#!/usr/bin/env python3
"""Point-in-time restore from a multi-part AOF directory (plan item 55).

Needs `aof-timestamp-enabled yes` (deploy/valkey.conf should set it) so the
server writes `#TS:<unix seconds>` annotations between commands.

  python3 pitr.py <appendonlydir> <out-dir> <unix-ts | ISO-8601>

Never modifies the source. Copies the base file and incr files in manifest order
into <out-dir>, cutting the stream at the first annotation later than the target,
and writes a matching manifest. Point a stopped node's appenddirname at <out-dir>
(or copy it over a scratch node) and start it to get the data as of that time.
"""
import datetime
import os
import shutil
import sys


def parse_ts(s):
    try:
        return int(s)
    except ValueError:
        d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            raise ValueError("ISO time needs a zone, e.g. 2026-11-01T01:00:00+08:00")
        return int(d.timestamp())


def read_manifest(path):
    entries = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            kv = dict(zip(parts[0::2], parts[1::2]))
            entries.append(kv)
    return entries


def cut(data, target):
    """Return (prefix, stopped): walk the RESP stream and stop before the first #TS > target.

    Bulk strings are skipped by length, so a value containing "#TS:" is never
    mistaken for an annotation.
    """
    pos, n = 0, len(data)
    while pos < n:
        end = data.find(b"\r\n", pos)
        if end == -1:
            return data, False
        head = data[pos:end]
        if head.startswith(b"#"):
            if head.startswith(b"#TS:"):
                try:
                    if int(head[4:]) > target:
                        return data[:pos], True
                except ValueError:
                    pass
            pos = end + 2
        elif head.startswith(b"*"):
            pos = end + 2
            for _ in range(int(head[1:])):
                e2 = data.find(b"\r\n", pos)
                if e2 == -1 or data[pos:pos + 1] != b"$":
                    raise ValueError("Corrupt AOF near byte %d" % pos)
                pos = e2 + 2 + int(data[pos + 1:e2]) + 2
        else:
            raise ValueError("Corrupt AOF near byte %d" % pos)
    return data, False


def restore(src, out, target):
    mf = [n for n in os.listdir(src) if n.endswith(".manifest")]
    if len(mf) != 1:
        raise SystemExit("Expected one .manifest in %s, found %d" % (src, len(mf)))
    entries = read_manifest(os.path.join(src, mf[0]))
    base = [e for e in entries if e.get("type") == "b"]
    incr = sorted((e for e in entries if e.get("type") == "i"), key=lambda e: int(e["seq"]))
    os.makedirs(out, exist_ok=False)
    kept = []
    for e in base:
        shutil.copyfile(os.path.join(src, e["file"]), os.path.join(out, e["file"]))
        kept.append(e)
    saw_ts = False
    for e in incr:
        with open(os.path.join(src, e["file"]), "rb") as f:
            data = f.read()
        saw_ts = saw_ts or b"#TS:" in data
        part, stopped = cut(data, target)
        with open(os.path.join(out, e["file"]), "wb") as f:
            f.write(part)
        kept.append(e)
        if stopped:
            break
    if incr and not saw_ts:
        raise SystemExit("No #TS annotations found; enable aof-timestamp-enabled first.")
    with open(os.path.join(out, mf[0]), "w") as f:
        for e in kept:
            f.write("file %s seq %s type %s\n" % (e["file"], e["seq"], e["type"]))
    return kept


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    restore(argv[1], argv[2], parse_ts(argv[3]))
    print("Restored copy written to %s" % argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
