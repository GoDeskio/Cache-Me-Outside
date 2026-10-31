#!/usr/bin/env python3
"""Encryption at rest for snapshots, AOF copies and backups (plan items 29, 30 BYOK).

Envelope encryption: each file gets a fresh 256-bit data key (AES-256-GCM,
streamed in 1 MiB chunks, each chunk authenticated with its index and a final
flag so chunks can't be reordered or cut). The data key is wrapped by a
per-tenant key-encryption key from a KeyProvider:

  LocalKeyProvider        KEK files on disk (home lab)
  EncryptoglyphProvider   wraps/unwraps through Encryptoglyph, so customers can
                          bring their own key (BYOK) and revoke it. Stub until
                          the Encryptoglyph key API is agreed; raises clearly.

Volumes themselves should also be encrypted (LUKS / cloud disk encryption);
this covers files that leave the node.

  python3 atrest.py encrypt <tenant> <in> <out> --kek-dir /etc/cmo/keks
  python3 atrest.py decrypt <in> <out> --kek-dir /etc/cmo/keks
"""
import argparse
import json
import os
import struct
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CMOENC1\n"
CHUNK = 1 << 20


class KeyProvider:
    def wrap(self, tenant, data_key):
        raise NotImplementedError

    def unwrap(self, tenant, wrapped):
        raise NotImplementedError


class LocalKeyProvider(KeyProvider):
    def __init__(self, kek_dir):
        self.dir = kek_dir

    def _kek(self, tenant):
        if not tenant.replace("-", "").replace("_", "").isalnum():
            raise ValueError("bad tenant id")
        p = os.path.join(self.dir, tenant + ".kek")
        if not os.path.exists(p):
            os.makedirs(self.dir, exist_ok=True)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(fd, AESGCM.generate_key(256))
            os.close(fd)
        with open(p, "rb") as f:
            return f.read()

    def wrap(self, tenant, data_key):
        n = os.urandom(12)
        return (n + AESGCM(self._kek(tenant)).encrypt(n, data_key, tenant.encode())).hex()

    def unwrap(self, tenant, wrapped):
        b = bytes.fromhex(wrapped)
        return AESGCM(self._kek(tenant)).decrypt(b[:12], b[12:], tenant.encode())


class EncryptoglyphProvider(KeyProvider):
    """BYOK through Encryptoglyph. Blocked: needs the agreed Encryptoglyph key API."""

    def wrap(self, tenant, data_key):
        raise NotImplementedError("Encryptoglyph key API not agreed yet (BYOK blocker)")

    unwrap = wrap


def _aad(i, last):
    return struct.pack(">QB", i, 1 if last else 0)


def encrypt(provider, tenant, src, dst):
    dk = AESGCM.generate_key(256)
    g = AESGCM(dk)
    prefix = os.urandom(4)
    hdr = json.dumps({"tenant": tenant, "wrapped": provider.wrap(tenant, dk), "alg": "A256GCM", "chunk": CHUNK}).encode()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + struct.pack(">I", len(hdr)) + hdr + prefix)
        i, cur = 0, fi.read(CHUNK)
        while True:
            nxt = fi.read(CHUNK)
            last = not nxt
            fo.write(g.encrypt(prefix + struct.pack(">Q", i), cur, _aad(i, last)))
            if last:
                break
            i, cur = i + 1, nxt


def decrypt(provider, src, dst):
    with open(src, "rb") as fi:
        if fi.read(len(MAGIC)) != MAGIC:
            raise ValueError("not a CMO encrypted file")
        hdr = json.loads(fi.read(struct.unpack(">I", fi.read(4))[0]))
        prefix = fi.read(4)
        g = AESGCM(provider.unwrap(hdr["tenant"], hdr["wrapped"]))
        size = hdr["chunk"] + 16
        tmp = dst + ".part"
        try:
            with open(tmp, "wb") as fo:
                i, cur = 0, fi.read(size)
                while True:
                    nxt = fi.read(size)
                    fo.write(g.decrypt(prefix + struct.pack(">Q", i), cur, _aad(i, not nxt)))
                    if not nxt:
                        break
                    i, cur = i + 1, nxt
            os.replace(tmp, dst)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["encrypt", "decrypt"])
    ap.add_argument("args", nargs="+")
    ap.add_argument("--kek-dir", default="/etc/cache-me-outside/keks")
    a = ap.parse_args(argv)
    p = LocalKeyProvider(a.kek_dir)
    if a.cmd == "encrypt":
        encrypt(p, *a.args)
    else:
        decrypt(p, *a.args)


if __name__ == "__main__":
    sys.exit(main())
