import unittest
import durable as D


def fake(local, remote, log):
    def call(*a):
        log.append(a)
        return [local, remote] if a[0] == "WAITAOF" else "OK"
    return call


class T(unittest.TestCase):
    def test_quorum(self):
        self.assertEqual([D.quorum(n) for n in (1, 2, 3, 4)], [1, 1, 2, 2])

    def test_ok(self):
        log = []
        c = D.DurableClient(fake(1, 2, log), replicas=3, timeout_ms=500)
        self.assertEqual(c.write("SET", "k", "v"), "OK")
        self.assertEqual(log[1], ("WAITAOF", "1", "2", "500"))

    def test_not_durable(self):
        with self.assertRaises(D.NotDurable):
            D.DurableClient(fake(1, 1, []), replicas=3).write("SET", "k", "v")
        with self.assertRaises(D.NotDurable):
            D.DurableClient(fake(0, 3, []), replicas=3).write("SET", "k", "v")
        with self.assertRaises(ValueError):
            D.DurableClient(fake(1, 1, []), replicas=0)


if __name__ == "__main__":
    unittest.main()
