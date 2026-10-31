import asyncio, sys, types, unittest, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cachemeoutside as cmo


def fake_glide(log):
    g = types.SimpleNamespace()
    g.ServerCredentials = lambda password, username=None: ("cred", username, password)
    g.NodeAddress = lambda h, p: (h, p)
    g.GlideClientConfiguration = lambda **kw: kw

    class Client:
        def __init__(s, cfg): s.cfg = cfg
        async def get(s, k): log.append(("get", k)); return b"v"
        async def set(s, k, v, **kw): log.append(("set", k, v)); return "OK"
        async def delete(s, ks): log.append(("del", ks)); return len(ks)
        async def close(s): log.append(("close",))

    async def create(cfg): return Client(cfg)
    g.GlideClient = types.SimpleNamespace(create=create)
    return g


class T(unittest.TestCase):
    def test_parse(self):
        i = cmo.parse_url("rediss://acme:p%40ss@cache.example:6380/2")
        self.assertEqual(i, cmo.ConnInfo("cache.example", 6380, True, "acme", "p@ss", 2))
        i = cmo.parse_url("redis://:pw@h")
        self.assertEqual((i.username, i.password, i.port, i.tls), (None, "pw", 6379, False))

    def test_bad(self):
        for u in ("http://h", "redis://", "redis://h/x"):
            with self.assertRaises(ValueError):
                cmo.parse_url(u)

    def test_config(self):
        cfg = cmo.glide_config(cmo.parse_url("rediss://u:p@h:1/3"), fake_glide([]))
        self.assertEqual(cfg["addresses"], [("h", 1)])
        self.assertTrue(cfg["use_tls"])
        self.assertEqual(cfg["credentials"], ("cred", "u", "p"))
        self.assertEqual(cfg["database_id"], 3)
        self.assertIsNone(cmo.glide_config(cmo.parse_url("redis://h"), fake_glide([]))["credentials"])

    def test_tenant(self):
        log = []
        async def run():
            c = await cmo.connect("redis://acme:p@h", prefix="acme", glide=fake_glide(log))
            await c.set("a", "1"); await c.get("acme:a"); await c.delete(["b"]); await c.close()
        asyncio.run(run())
        self.assertEqual(log, [("set", "acme:a", "1"), ("get", "acme:a"),
                               ("del", ["acme:b"]), ("close",)])

    def test_bad_prefix(self):
        for p in ("", "a*", "a b"):
            with self.assertRaises(ValueError):
                cmo.TenantClient(object(), p)


if __name__ == "__main__":
    unittest.main()
