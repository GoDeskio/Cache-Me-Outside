import os
import unittest
import chunking


class Mem(dict):
    def get(self, k): return dict.get(self, k)
    def set(self, k, v, ttl=None): self[k] = v; return True
    def delete(self, k): return self.pop(k, None) is not None


class T(unittest.TestCase):
    def test_small_passthrough(self):
        m = Mem(); chunking.put(m, "k", b"hi", chunk_size=10)
        self.assertEqual(m["k"], b"hi")
        self.assertEqual(chunking.get(m, "k"), b"hi")

    def test_roundtrip_and_delete(self):
        m = Mem(); data = os.urandom(10_000)
        chunking.put(m, "k", data, chunk_size=1000)
        self.assertEqual(len(m), 11)
        self.assertEqual(chunking.get(m, "k"), data)
        chunking.delete(m, "k")
        self.assertEqual(len(m), 0)

    def test_torn_is_miss(self):
        m = Mem(); chunking.put(m, "k", os.urandom(3000), chunk_size=1000)
        part = next(k for k in m if k.endswith(":1"))
        m[part] = b"x" * 1000
        self.assertIsNone(chunking.get(m, "k"))
        del m[part]
        self.assertIsNone(chunking.get(m, "k"))


if __name__ == "__main__":
    unittest.main()
