"""Cache Me Outside Python SDK: a thin wrapper over valkey-glide.

It parses a CMO connection URL into a Glide configuration and keeps every
key inside the tenant's prefix, which is what the per-tenant ACLs allow.
valkey-glide is imported only when connect() is called.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, unquote

__all__ = ["ConnInfo", "parse_url", "glide_config", "connect", "TenantClient"]
__version__ = "0.1.0"


@dataclass(frozen=True)
class ConnInfo:
    host: str
    port: int
    tls: bool
    username: Optional[str]
    password: Optional[str]
    db: int = 0


def parse_url(url: str) -> ConnInfo:
    u = urlparse(url)
    if u.scheme not in ("redis", "rediss", "valkey", "valkeys"):
        raise ValueError("unsupported scheme: %r" % u.scheme)
    if not u.hostname:
        raise ValueError("missing host")
    db = 0
    path = (u.path or "").strip("/")
    if path:
        if not path.isdigit():
            raise ValueError("db must be a number")
        db = int(path)
    user = unquote(u.username) if u.username else None
    pw = unquote(u.password) if u.password is not None else None
    if user == "":
        user = None
    return ConnInfo(u.hostname, u.port or 6379, u.scheme in ("rediss", "valkeys"), user, pw, db)


def glide_config(info: ConnInfo, glide=None):
    if glide is None:
        import glide  # noqa: F811  (optional dependency)
    creds = None
    if info.password is not None:
        creds = glide.ServerCredentials(password=info.password, username=info.username)
    return glide.GlideClientConfiguration(
        addresses=[glide.NodeAddress(info.host, info.port)],
        use_tls=info.tls, credentials=creds, database_id=info.db)


async def connect(url: str, prefix: Optional[str] = None, glide=None):
    """Return a Glide client; if prefix is given, wrap it in TenantClient."""
    if glide is None:
        import glide  # noqa: F811
    client = await glide.GlideClient.create(glide_config(parse_url(url), glide))
    return TenantClient(client, prefix) if prefix else client


class TenantClient:
    """Prefixes keys so commands stay within the tenant ACL (~prefix:*)."""

    def __init__(self, client, prefix: str):
        if not prefix or any(c in prefix for c in "*?[] "):
            raise ValueError("invalid prefix")
        self.raw = client
        self.prefix = prefix if prefix.endswith(":") else prefix + ":"

    def key(self, k: str) -> str:
        return k if k.startswith(self.prefix) else self.prefix + k

    async def get(self, k):
        return await self.raw.get(self.key(k))

    async def set(self, k, v, **kw):
        return await self.raw.set(self.key(k), v, **kw)

    async def delete(self, keys):
        return await self.raw.delete([self.key(k) for k in keys])

    async def exists(self, keys):
        return await self.raw.exists([self.key(k) for k in keys])

    async def incr(self, k):
        return await self.raw.incr(self.key(k))

    async def expire(self, k, seconds):
        return await self.raw.expire(self.key(k), seconds)

    async def close(self):
        return await self.raw.close()
