#!/usr/bin/env python3
"""Cloud object-storage tier: spill snapshots/AOF to S3 or R2 (plan item 26).

- sign(): AWS Signature V4 (stdlib only; works for S3 and Cloudflare R2).
- S3Store: put/get/list/delete over HTTPS. Credentials come from env vars.
- Spiller: upload a new snapshot with a sha256 check, then keep the newest N
  plus one per day for D days and delete the rest.
"""
import datetime
import hashlib
import hmac
import os
import urllib.parse
import urllib.request

EMPTY = hashlib.sha256(b"").hexdigest()


def _h(k, m):
    return hmac.new(k, m.encode(), hashlib.sha256).digest()


def sign(method, host, path, query, headers, payload_hash, key_id, secret, region, amz_date, service="s3"):
    day = amz_date[:8]
    hdrs = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    hdrs["host"] = host
    hdrs["x-amz-content-sha256"] = payload_hash
    hdrs["x-amz-date"] = amz_date
    names = sorted(hdrs)
    canon_q = "&".join("%s=%s" % (urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~"))
                       for k, v in sorted(query.items()))
    creq = "\n".join([method, urllib.parse.quote(path, safe="/-_.~"), canon_q,
                      "".join("%s:%s\n" % (n, hdrs[n]) for n in names), ";".join(names), payload_hash])
    scope = "%s/%s/%s/aws4_request" % (day, region, service)
    sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = _h(_h(_h(_h(("AWS4" + secret).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    hdrs["authorization"] = "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (
        key_id, scope, ";".join(names), sig)
    return hdrs


class S3Store:
    """endpoint e.g. https://<acct>.r2.cloudflarestorage.com ; path-style bucket."""

    def __init__(self, endpoint, bucket, region="auto"):
        self.ep, self.bucket, self.region = endpoint.rstrip("/"), bucket, region
        self.kid, self.sec = os.environ["CMO_S3_KEY_ID"], os.environ["CMO_S3_SECRET"]

    def _req(self, method, key="", body=b"", query=None):
        u = urllib.parse.urlparse(self.ep)
        path = "/%s/%s" % (self.bucket, key) if key else "/%s" % self.bucket
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        h = sign(method, u.netloc, path, query or {}, {}, hashlib.sha256(body).hexdigest(),
                 self.kid, self.sec, self.region, date)
        url = self.ep + urllib.parse.quote(path) + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(url, data=body or None, method=method,
                                     headers={k: v for k, v in h.items() if k != "host"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    def put(self, key, data): self._req("PUT", key, data)
    def get(self, key): return self._req("GET", key)
    def delete(self, key): self._req("DELETE", key)

    def list(self, prefix):
        import xml.etree.ElementTree as ET
        x = ET.fromstring(self._req("GET", query={"list-type": "2", "prefix": prefix}))
        return [e.text for e in x.iter() if e.tag.endswith("Key")]


class Spiller:
    def __init__(self, store, prefix="snap/", keep_last=5, keep_daily=14):
        self.s, self.p, self.last, self.daily = store, prefix, keep_last, keep_daily

    def upload(self, data, when):
        key = "%s%s.rdb" % (self.p, when.strftime("%Y%m%dT%H%M%SZ"))
        self.s.put(key, data)
        if hashlib.sha256(self.s.get(key)).digest() != hashlib.sha256(data).digest():
            raise IOError("upload verify failed for " + key)
        return key

    def prune(self, now):
        keys = sorted(self.s.list(self.p), reverse=True)
        keep, days = set(keys[:self.last]), set()
        for k in keys:
            ts = datetime.datetime.strptime(k[len(self.p):len(self.p) + 15], "%Y%m%dT%H%M%S").replace(
                tzinfo=datetime.timezone.utc)
            if (now - ts).days < self.daily and ts.date() not in days:
                days.add(ts.date())
                keep.add(k)
        gone = [k for k in keys if k not in keep]
        for k in gone:
            self.s.delete(k)
        return gone
