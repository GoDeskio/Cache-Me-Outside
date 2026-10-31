import os
import tempfile
import unittest
import pitr


def cmd(*a):
    return b"*%d\r\n" % len(a) + b"".join(b"$%d\r\n%s\r\n" % (len(x), x) for x in a)


class T(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.src = os.path.join(self.d, "aof")
        os.mkdir(self.src)
        open(os.path.join(self.src, "a.base.rdb"), "wb").write(b"REDIS-base")
        open(os.path.join(self.src, "a.incr.1.aof"), "wb").write(
            b"#TS:100\r\n" + cmd(b"SET", b"k", b"1") + b"#TS:200\r\n" + cmd(b"SET", b"k", b"2"))
        open(os.path.join(self.src, "a.incr.2.aof"), "wb").write(b"#TS:300\r\n" + cmd(b"SET", b"k", b"#TS:999"))
        open(os.path.join(self.src, "a.aof.manifest"), "w").write(
            "file a.base.rdb seq 1 type b\nfile a.incr.1.aof seq 1 type i\nfile a.incr.2.aof seq 2 type i\n")

    def test_cut_mid_file(self):
        out = os.path.join(self.d, "o")
        pitr.restore(self.src, out, 150)
        data = open(os.path.join(out, "a.incr.1.aof"), "rb").read()
        self.assertIn(b"$1\r\n1", data)
        self.assertNotIn(b"$1\r\n2", data)
        self.assertFalse(os.path.exists(os.path.join(out, "a.incr.2.aof")))
        self.assertNotIn("incr.2", open(os.path.join(out, "a.aof.manifest")).read())
        self.assertEqual(open(os.path.join(out, "a.base.rdb"), "rb").read(), b"REDIS-base")

    def test_value_that_looks_like_ts_is_kept(self):
        out = os.path.join(self.d, "o2")
        pitr.restore(self.src, out, 500)
        self.assertIn(b"#TS:999", open(os.path.join(out, "a.incr.2.aof"), "rb").read())

    def test_source_untouched_and_out_must_be_new(self):
        before = open(os.path.join(self.src, "a.incr.1.aof"), "rb").read()
        pitr.restore(self.src, os.path.join(self.d, "o3"), 0)
        self.assertEqual(before, open(os.path.join(self.src, "a.incr.1.aof"), "rb").read())
        with self.assertRaises(FileExistsError):
            pitr.restore(self.src, os.path.join(self.d, "o3"), 0)

    def test_parse_ts(self):
        self.assertEqual(pitr.parse_ts("100"), 100)
        self.assertEqual(pitr.parse_ts("1970-01-01T08:00:10+08:00"), 10)
        with self.assertRaises(ValueError):
            pitr.parse_ts("2026-11-01T01:00:00")


if __name__ == "__main__":
    unittest.main()
