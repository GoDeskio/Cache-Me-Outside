import os
import stat
import tempfile
import unittest
from cryptography.exceptions import InvalidTag
import atrest as A


class T(unittest.TestCase):
    def setUp(self):
        A.CHUNK = 1000
        self.d = tempfile.mkdtemp()
        self.p = A.LocalKeyProvider(os.path.join(self.d, "keks"))
        self.src = os.path.join(self.d, "dump.rdb")
        self.data = os.urandom(3500)
        open(self.src, "wb").write(self.data)

    def f(self, n):
        return os.path.join(self.d, n)

    def test_roundtrip_and_kek_perms(self):
        A.encrypt(self.p, "acme", self.src, self.f("e"))
        self.assertNotIn(self.data[:50], open(self.f("e"), "rb").read())
        A.decrypt(self.p, self.f("e"), self.f("out"))
        self.assertEqual(open(self.f("out"), "rb").read(), self.data)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.d, "keks", "acme.kek")).st_mode), 0o600)

    def test_empty_file(self):
        open(self.src, "wb").close()
        A.encrypt(self.p, "acme", self.src, self.f("e"))
        A.decrypt(self.p, self.f("e"), self.f("out"))
        self.assertEqual(open(self.f("out"), "rb").read(), b"")

    def test_truncation_and_tamper_detected(self):
        A.encrypt(self.p, "acme", self.src, self.f("e"))
        raw = open(self.f("e"), "rb").read()
        open(self.f("cut"), "wb").write(raw[:-(len(raw) - 1000) // 2])
        with self.assertRaises(InvalidTag):
            A.decrypt(self.p, self.f("cut"), self.f("o1"))
        self.assertFalse(os.path.exists(self.f("o1")))
        bad = bytearray(raw)
        bad[-5] ^= 1
        open(self.f("bad"), "wb").write(bad)
        with self.assertRaises(InvalidTag):
            A.decrypt(self.p, self.f("bad"), self.f("o2"))

    def test_other_tenant_key_fails(self):
        A.encrypt(self.p, "acme", self.src, self.f("e"))
        raw = open(self.f("e"), "rb").read().replace(b'"tenant": "acme"', b'"tenant": "evil"')
        open(self.f("x"), "wb").write(raw)
        with self.assertRaises(InvalidTag):
            A.decrypt(self.p, self.f("x"), self.f("o"))
        with self.assertRaises(ValueError):
            self.p.wrap("../etc", b"k" * 32)

    def test_byok_stub(self):
        with self.assertRaises(NotImplementedError):
            A.encrypt(A.EncryptoglyphProvider(), "acme", self.src, self.f("e"))


if __name__ == "__main__":
    unittest.main()
