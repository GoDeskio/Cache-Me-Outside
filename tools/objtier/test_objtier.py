import datetime as dt
import unittest
import objtier as O


class Mem:
    def __init__(self): self.d = {}
    def put(self, k, v): self.d[k] = v
    def get(self, k): return self.d[k]
    def delete(self, k): del self.d[k]
    def list(self, p): return [k for k in self.d if k.startswith(p)]


class T(unittest.TestCase):
    def test_sigv4_aws_example(self):
        # Example from the AWS S3 SigV4 docs (GET object with Range).
        h = O.sign("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {}, {"Range": "bytes=0-9"},
                   O.EMPTY, "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                   "us-east-1", "20130524T000000Z")
        self.assertTrue(h["authorization"].endswith(
            "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"))
        self.assertIn("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date", h["authorization"])

    def test_upload_and_prune(self):
        m = Mem()
        s = O.Spiller(m, keep_last=2, keep_daily=3)
        t0 = dt.datetime(2026, 11, 1, 12, tzinfo=dt.timezone.utc)
        for d in range(6):
            for hr in (0, 6):
                s.upload(b"x", t0 - dt.timedelta(days=d, hours=hr))
        gone = s.prune(t0)
        left = sorted(m.d)
        self.assertEqual(len(left), 4)  # newest 2 (same day) + 1/day for 2 older days
        self.assertTrue(all(k not in m.d for k in gone))
        self.assertIn("snap/20261101T120000Z.rdb", left)


if __name__ == "__main__":
    unittest.main()
