import unittest
import procs as P

GOOD = """
local function incr_by(keys, args)
  -- os.exit is not called, this comment is fine
  return server.call('INCRBY', keys[1], args[1])
end
server.register_function('acme_incr', incr_by)
server.register_function{function_name='acme_ro', callback=incr_by, flags={'no-writes'}}
"""


class T(unittest.TestCase):
    def test_good(self):
        argv, fns = P.prepare("acme", "counters", GOOD)
        self.assertEqual(argv[:3], ["FUNCTION", "LOAD", "REPLACE"])
        self.assertTrue(argv[3].startswith("#!lua name=acme_counters\n"))
        self.assertEqual(fns, ["acme_incr", "acme_ro"])

    def test_rejects(self):
        for src in ["local x = loadstring('return 1')\nserver.register_function('acme_a', x)",
                    "os.execute('x')\nserver.register_function('acme_a', f)",
                    "local t = setmetatable({}, {})\nserver.register_function('acme_a', f)",
                    "server.register_function('other_a', f)",
                    "return 1",
                    "x" * (P.MAX_BYTES + 1)]:
            with self.assertRaises(ValueError, msg=src[:30]):
                P.prepare("acme", "lib", src)
        with self.assertRaises(ValueError):
            P.prepare("Acme!", "lib", GOOD)

    def test_call_scope(self):
        self.assertEqual(P.call("acme_incr", ["acme:c"], ["1"], "acme"), ["FCALL", "acme_incr", "1", "acme:c", "1"])
        with self.assertRaises(PermissionError):
            P.call("bob_incr", ["acme:c"], [], "acme")
        with self.assertRaises(PermissionError):
            P.call("acme_incr", ["bob:c"], [], "acme")


if __name__ == "__main__":
    unittest.main()
