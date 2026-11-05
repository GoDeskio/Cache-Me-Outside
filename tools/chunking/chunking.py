"""Large-value chunking (plan #82). Independent rebuild; stdlib only.

Values above chunk_size are split into <key>:c:<gen>:<i> parts plus a manifest at
<key> holding generation, count and SHA-256. Readers verify the digest, so a torn
write (some parts missing or from another generation) reads as a miss.
"""
import hashlib
import json
import uuid

MAGIC = b"CMOCHUNK1"


def put(h, key, value: bytes, chunk_size=512 * 1024, ttl=None):
    if len(value) <= chunk_size:
        return h.set(key, value, ttl=ttl)
    gen = uuid.uuid4().hex[:12]
    parts = [value[i:i + chunk_size] for i in range(0, len(value), chunk_size)]
    for i, p in enumerate(parts):
        h.set(f"{key}:c:{gen}:{i}", p, ttl=ttl)
    man = {"gen": gen, "n": len(parts), "len": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    return h.set(key, MAGIC + json.dumps(man).encode(), ttl=ttl)


def get(h, key):
    v = h.get(key)
    if v is None or not v.startswith(MAGIC):
        return v
    man = json.loads(v[len(MAGIC):])
    buf = []
    for i in range(man["n"]):
        p = h.get(f"{key}:c:{man['gen']}:{i}")
        if p is None:
            return None
        buf.append(p)
    out = b"".join(buf)
    if len(out) != man["len"] or hashlib.sha256(out).hexdigest() != man["sha256"]:
        return None
    return out


def delete(h, key):
    v = h.get(key)
    if v is not None and v.startswith(MAGIC):
        man = json.loads(v[len(MAGIC):])
        for i in range(man["n"]):
            h.delete(f"{key}:c:{man['gen']}:{i}")
    return h.delete(key)
