import unittest
import diskplan as D


class T(unittest.TestCase):
    def test_config(self):
        c = D.config(200)
        self.assertIn("rocksdb.block_cache_size 2048", c)
        self.assertIn("tls-port 6380", c)
        self.assertIn("port 0", c)
        self.assertNotIn("requirepass", c)
        self.assertIn("port 6379", D.config(50, tls=False))
        with self.assertRaises(ValueError):
            D.config(7)

    def test_commands(self):
        self.assertIsNone(D.check_command(["GET", "k"]))
        self.assertIsNone(D.check_command(["hset", "h", "f", "v"]))
        self.assertIn("not available", D.check_command(["ft.search", "i", "*"]))
        self.assertIn("not available", D.check_command(["TS.ADD", "k", "*", "1"]))
        self.assertIn("not available", D.check_command(["MODULE", "LIST"]))


if __name__ == "__main__":
    unittest.main()
