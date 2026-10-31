import unittest
from semcache import SemanticCache, cosine

WORDS = ["capital", "france", "paris", "weather", "today", "what", "is", "the", "of"]


def bag(text):
    t = text.lower().replace("?", "").split()
    return [float(t.count(w)) for w in WORDS]


class T(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.c = SemanticCache(bag, threshold=0.9, ttl=60, clock=lambda: self.now[0])

    def test_hit_on_similar(self):
        self.c.put("t1", "What is the capital of France?", "Paris")
        self.assertEqual(self.c.get("t1", "what is the capital of france")["answer"], "Paris")
        self.assertIsNone(self.c.get("t1", "weather today"))

    def test_tenant_isolation(self):
        self.c.put("t1", "capital of france", "Paris")
        self.assertIsNone(self.c.get("t2", "capital of france"))

    def test_ttl(self):
        self.c.put("t1", "capital of france", "Paris")
        self.now[0] += 61
        self.assertIsNone(self.c.get("t1", "capital of france"))
        self.assertEqual(len(self.c.index.rows), 0)

    def test_get_or_call(self):
        calls = []
        llm = lambda p: calls.append(p) or "Paris"
        self.assertEqual(self.c.get_or_call("t", "capital of france", llm), ("Paris", False))
        self.assertEqual(self.c.get_or_call("t", "Capital of France?", llm), ("Paris", True))
        self.assertEqual(len(calls), 1)

    def test_cosine_and_bad_threshold(self):
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)
        with self.assertRaises(ValueError):
            SemanticCache(bag, threshold=0)


if __name__ == "__main__":
    unittest.main()
