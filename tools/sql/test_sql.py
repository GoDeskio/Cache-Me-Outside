import unittest
from sql import translate as T


class X(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(T("SELECT * FROM users"), ["FT.SEARCH", "users", "*"])
        self.assertEqual(T("select name, age from users where age >= 18 and city = 'New York' order by age desc limit 10 offset 20;"),
                         ["FT.SEARCH", "users", "@age:[18 +inf] @city:{New\\ York}", "RETURN", "2", "name", "age",
                          "SORTBY", "age", "DESC", "LIMIT", "20", "10"])

    def test_ops(self):
        self.assertEqual(T("SELECT * FROM i WHERE p BETWEEN 1 AND 5")[2], "@p:[1 5]")
        self.assertEqual(T("SELECT * FROM i WHERE p < 3")[2], "@p:[-inf (3]")
        self.assertEqual(T("SELECT * FROM i WHERE c IN ('a','b-c')")[2], "@c:{a | b\\-c}")
        self.assertEqual(T("SELECT COUNT(*) FROM i WHERE p > 2"), ["FT.SEARCH", "i", "@p:[(2 +inf]", "LIMIT", "0", "0"])

    def test_rejects(self):
        for bad in ("DELETE FROM i", "SELECT * FROM i; DROP TABLE x", "SELECT * FROM i WHERE a LIKE 'x'",
                    "SELECT * FROM i WHERE a > 'x'", "SELECT * FROM i WHERE a = 1 OR b = 2", "SELECT * FROM i@x"):
            with self.assertRaises(ValueError, msg=bad):
                T(bad)

    def test_escapes_injection(self):
        q = T("SELECT * FROM i WHERE c = '} | @x:{y'")[2]
        self.assertEqual(q, "@c:{\\}\\ \\|\\ \\@x\\:\\{y}")


if __name__ == "__main__":
    unittest.main()
