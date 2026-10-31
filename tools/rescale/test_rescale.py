import unittest
import rescale as R


def even(nodes):
    o = []
    for n, c in sorted(R.targets(nodes).items()):
        o += [n] * c
    return o


class T(unittest.TestCase):
    def check(self, owner, nodes):
        moves = R.plan(owner, nodes)
        out = R.apply(moves, owner)
        counts = {n: out.count(n) for n in nodes}
        self.assertEqual(set(out), set(nodes))
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        moved = sum(b - a + 1 for _, _, a, b in moves)
        return moves, moved

    def test_scale_out_minimal(self):
        moves, moved = self.check(even(["a", "b", "c"]), ["a", "b", "c", "d"])
        self.assertEqual(moved, 4096)  # only d's share moves
        self.assertTrue(all(d == "d" for _, d, _, _ in moves))
        self.assertLessEqual(len(moves), 3)  # contiguous ranges

    def test_scale_in_and_replace(self):
        _, moved = self.check(even(["a", "b", "c", "d"]), ["a", "b", "c"])
        self.assertEqual(moved, 4096)
        _, moved = self.check(even(["a", "b"]), ["a", "big"])  # vertical: swap b
        self.assertEqual(moved, 8192)

    def test_noop_and_commands(self):
        self.assertEqual(R.plan(even(["a", "b"]), ["a", "b"]), [])
        src, cmd = R.commands([("a", "d", 0, 99)])[0]
        self.assertEqual((src, cmd), ("a", ["CLUSTER", "MIGRATESLOTS", "SLOTSRANGE", "0", "99", "NODE", "d"]))
        with self.assertRaises(ValueError):
            R.plan(["a"], ["a"])


if __name__ == "__main__":
    unittest.main()
