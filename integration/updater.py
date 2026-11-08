"""Update the integration directory from a published GitHub release.

  python3 integration/updater.py --check
  python3 integration/updater.py --apply

A release tag looks like cmo-integration-v1.2.3 and carries
cache-me-outside-integration.tar.gz plus SHA256SUMS. The archive is applied
only after the checksum matches, and only the known filenames are written.
Nothing in this file is a secret, and a missing release is not an error.
"""
import hashlib
import io
import json
import os
import tarfile
import urllib.request
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ASSET = "cache-me-outside-integration.tar.gz"
ALLOW = {"manifest.json", "cache_me_outside.py", "cache-me-outside.js", "sidecar.py", "updater.py"}
HOSTS = ("api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
DEFAULT_API = "https://api.github.com/repos/GoDeskio/Cache-Me-Outside/releases?per_page=20"


def local_version(path=None):
    with open(os.path.join(path or HERE, "manifest.json")) as handle:
        return json.load(handle)["version"]


def semver(text):
    parts = text.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("bad version %r" % text)
    return tuple(int(part) for part in parts)


def allow_for(api):
    base = urlsplit(api)

    def allow(url):
        got = urlsplit(url)
        if base.hostname in ("127.0.0.1", "localhost"):
            return got.scheme == base.scheme and got.netloc == base.netloc
        return got.scheme == "https" and got.hostname in HOSTS
    return allow


class _Guard(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow):
        self.allow = allow

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.allow(newurl):
            raise ValueError("redirect refused")
        return urllib.request.HTTPRedirectHandler.redirect_request(self, req, fp, code, msg, headers, newurl)


def _get(url, allow, limit=2000000):
    if not allow(url):
        raise ValueError("refusing " + url)
    opener = urllib.request.build_opener(_Guard(allow))
    with opener.open(url, timeout=20) as response:
        blob = response.read(limit + 1)
    if len(blob) > limit:
        raise ValueError("download is too large")
    return blob


def choose(releases, prefix="cmo-integration-v"):
    best = None
    best_key = None
    for release in releases:
        tag = release.get("tag_name") or ""
        if not tag.startswith(prefix):
            continue
        key = semver(tag[len(prefix):])
        if best_key is None or key > best_key:
            best, best_key = release, key
    return best


def checksum(text, filename):
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].endswith(filename) and len(parts[0]) == 64:
            return parts[0]
    raise ValueError("checksum missing")


def unpack(blob):
    archive = tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz")
    chosen = {}
    for member in archive.getmembers():
        if member.isdir():
            continue
        parts = member.name.split("/")
        if member.issym() or member.islnk() or not member.isfile() or any(part in ("", "..") for part in parts):
            raise ValueError("refusing %s" % member.name)
        base = parts[-1]
        if base not in ALLOW or base in chosen:
            raise ValueError("unexpected file %s" % member.name)
        data = archive.extractfile(member).read()
        if len(data) > 200000:
            raise ValueError("file too large")
        chosen[base] = data
    if "manifest.json" not in chosen:
        raise ValueError("manifest missing")
    json.loads(chosen["manifest.json"].decode())
    return chosen


def apply_files(files, dest):
    os.makedirs(dest, exist_ok=True)
    for name, data in files.items():
        target = os.path.join(dest, name)
        if os.path.dirname(os.path.abspath(target)) != os.path.abspath(dest):
            raise ValueError("refusing to write outside the integration directory")
        tmp = target + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(data)
        os.replace(tmp, target)


def check(api=DEFAULT_API, dest=None):
    dest = dest or HERE
    current = semver(local_version(dest))
    allow = allow_for(api)
    try:
        releases = json.loads(_get(api, allow).decode())
    except Exception as exc:
        return {"status": "unreachable", "version": "%d.%d.%d" % current, "detail": str(exc)}
    if not isinstance(releases, list):
        return {"status": "unreachable", "version": "%d.%d.%d" % current, "detail": "unexpected release list"}
    release = choose(releases)
    if not release:
        return {"status": "none", "version": "%d.%d.%d" % current}
    remote = semver(release["tag_name"][len("cmo-integration-v"):])
    return {
        "status": "update" if remote > current else "current",
        "version": "%d.%d.%d" % current,
        "remote": "%d.%d.%d" % remote,
        "release": release,
    }


def apply(api=DEFAULT_API, dest=None):
    dest = dest or HERE
    found = check(api, dest)
    if found["status"] != "update":
        return found
    allow = allow_for(api)
    assets = {item.get("name"): item.get("browser_download_url") for item in found["release"].get("assets") or []}
    if ASSET not in assets or "SHA256SUMS" not in assets:
        raise ValueError("release is missing the archive or SHA256SUMS")
    blob = _get(assets[ASSET], allow)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != checksum(_get(assets["SHA256SUMS"], allow).decode(), ASSET):
        raise ValueError("checksum did not match; nothing was written")
    apply_files(unpack(blob), dest)
    found["status"] = "applied"
    found["version"] = local_version(dest)
    return found


def main(argv=None):
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Cache Me Outside integration updater")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--api", default=os.environ.get("CMO_RELEASE_API", DEFAULT_API))
    ap.add_argument("--dest", default=HERE)
    a = ap.parse_args(argv)
    if a.apply == a.check:
        ap.error("choose --check or --apply")
    try:
        result = apply(a.api, a.dest) if a.apply else check(a.api, a.dest)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result["status"] + " " + result.get("remote", result["version"]))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
