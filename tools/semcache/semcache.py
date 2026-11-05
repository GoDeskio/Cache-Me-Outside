#!/usr/bin/env python3
"""Semantic LLM response cache (plan item 71). Built from scratch, stdlib only.

Store a prompt's embedding with the model's answer; a later prompt whose
embedding is within `threshold` cosine similarity returns the cached answer.

Pieces are interfaces so they can be swapped:
  Embedder   embed(text) -> list[float]    (plug in any embedding API)
  Index      add / search / delete         MemoryIndex here; a valkey-search
                                           (HNSW, item 70) index can implement
                                           the same three methods.
Entries expire after `ttl` seconds and are partitioned by namespace (tenant/model)
so one tenant never sees another's answers.
"""
import math
import time
import uuid


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


class MemoryIndex:
    def __init__(self):
        self.rows = {}

    def add(self, ns, id_, vec, payload):
        self.rows[id_] = (ns, vec, payload)

    def search(self, ns, vec, k=1):
        hits = [(cosine(vec, v), i, p) for i, (n, v, p) in self.rows.items() if n == ns]
        hits.sort(key=lambda h: -h[0])
        return hits[:k]

    def delete(self, id_):
        self.rows.pop(id_, None)


class SemanticCache:
    def __init__(self, embedder, index=None, threshold=0.92, ttl=3600, clock=time.time):
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be in (0, 1]")
        self.embed = embedder
        self.index = index or MemoryIndex()
        self.threshold = threshold
        self.ttl = ttl
        self.clock = clock
        self.hits = self.misses = 0

    def get(self, ns, prompt):
        vec = self.embed(prompt)
        for score, id_, p in self.index.search(ns, vec, k=3):
            if p["expires"] <= self.clock():
                self.index.delete(id_)
                continue
            if score >= self.threshold:
                self.hits += 1
                return {"answer": p["answer"], "score": round(score, 4), "prompt": p["prompt"]}
            break
        self.misses += 1
        return None

    def put(self, ns, prompt, answer, ttl=None):
        id_ = uuid.uuid4().hex
        self.index.add(ns, id_, self.embed(prompt),
                       {"prompt": prompt, "answer": answer, "expires": self.clock() + (ttl or self.ttl)})
        return id_

    def get_or_call(self, ns, prompt, llm):
        hit = self.get(ns, prompt)
        if hit:
            return hit["answer"], True
        ans = llm(prompt)
        self.put(ns, prompt, ans)
        return ans, False
