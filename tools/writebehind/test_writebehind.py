import sqlite3
import unittest
import writebehind as W


class FakeStream:
    def __init__(self, recs):
        self.pending = [(str(i), r) for i, r in enumerate(recs)]
        self.acked, self.dlq = [], []

    def read(self, n):
        return [m for m in self.pending if m[0] not in self.acked][:n]

    def ack(self, ids):
        self.acked += ids

    def dead_letter(self, mid, f, err):
        self.dlq.append((mid, err))


class T(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.sink = W.SqliteSink(self.db, "users")

    def rows(self):
        return dict(self.db.execute("SELECT id, data FROM users").fetchall())

    def test_batch_upsert_delete(self):
        s = FakeStream([{"op": "upsert", "id": "1", "data": '{"n":1}'},
                        {"op": "upsert", "id": "1", "data": '{"n":2}'},
                        {"op": "upsert", "id": "2", "data": "{}"},
                        {"op": "delete", "id": "2"}])
        self.assertEqual(W.Worker(s, self.sink).step(), 4)
        self.assertEqual(self.rows(), {"1": '{"n":2}'})
        self.assertEqual(len(s.acked), 4)

    def test_bad_record_isolated_then_dead_lettered(self):
        s = FakeStream([{"op": "upsert", "id": "1", "data": "{}"},
                        {"op": "upsert", "id": "2", "data": "not json"}])
        w = W.Worker(s, self.sink, max_tries=2)
        self.assertEqual(w.step(), 1)
        self.assertEqual(self.rows(), {"1": "{}"})
        self.assertEqual(s.dlq, [])
        w.step()
        self.assertEqual([d[0] for d in s.dlq], ["1"])
        self.assertEqual(sorted(s.acked), ["0", "1"])

    def test_rollback_on_failure_and_names(self):
        s = FakeStream([{"op": "upsert", "id": "a", "data": "{}"}, {"op": "boom", "id": "b"}])
        W.Worker(s, self.sink, max_tries=1).step()
        self.assertEqual(self.rows(), {"a": "{}"})
        self.assertEqual(len(s.dlq), 1)
        with self.assertRaises(ValueError):
            W.SqliteSink(self.db, 'x"; DROP TABLE users;--')
        W.write_through(self.sink, {"op": "upsert", "id": "z", "data": "[]"})
        self.assertIn("z", self.rows())


if __name__ == "__main__":
    unittest.main()
