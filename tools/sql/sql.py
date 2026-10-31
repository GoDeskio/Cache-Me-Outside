#!/usr/bin/env python3
"""SQL over cached data (plan item 68), built on the search module (#69/#70).

Translates a small read-only SQL subset into FT.SEARCH / FT.AGGREGATE:
  SELECT a, b | * | COUNT(*) FROM <index> [WHERE cond [AND cond]...]
  [ORDER BY f [ASC|DESC]] [LIMIT n [OFFSET m]]
cond: f = 'text' | f = num | f > num | f >= | < | <= | f BETWEEN x AND y | f IN ('a','b')
Anything else is rejected; there is no write path.
"""
import re

TOK = re.compile(r"\s*(>=|<=|!=|[(),*=<>]|'(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*)")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _toks(s):
    out, i, s = [], 0, s.strip().rstrip(";")
    while i < len(s):
        m = TOK.match(s, i)
        if not m:
            raise ValueError("cannot parse near %r" % s[i:i + 10])
        out.append(m.group(1))
        i = m.end()
    return out


def _esc(v):
    return re.sub(r"([^A-Za-z0-9_])", r"\\\1", v)


class P:
    def __init__(self, t): self.t, self.i = t, 0
    def peek(self): return self.t[self.i].upper() if self.i < len(self.t) else None
    def take(self, want=None):
        if self.i >= len(self.t):
            raise ValueError("unexpected end")
        v = self.t[self.i]
        if want and v.upper() != want:
            raise ValueError("expected %s got %s" % (want, v))
        self.i += 1
        return v
    def ident(self):
        v = self.take()
        if not IDENT.match(v):
            raise ValueError("bad identifier %r" % v)
        return v
    def num(self):
        v = self.take()
        float(v)
        return v


def _cond(p):
    f = p.ident()
    op = p.take().upper()
    if op == "BETWEEN":
        a = p.num(); p.take("AND"); b = p.num()
        return "@%s:[%s %s]" % (f, a, b)
    if op == "IN":
        p.take("(")
        vals = [p.take()]
        while p.peek() == ",":
            p.take(); vals.append(p.take())
        p.take(")")
        return "@%s:{%s}" % (f, " | ".join(_esc(v.strip("'")) for v in vals))
    v = p.take()
    if v.startswith("'"):
        if op != "=":
            raise ValueError("only = for text")
        return "@%s:{%s}" % (f, _esc(v[1:-1]))
    float(v)
    rng = {"=": "[%s %s]" % (v, v), ">": "[(%s +inf]" % v, ">=": "[%s +inf]" % v,
           "<": "[-inf (%s]" % v, "<=": "[-inf %s]" % v}
    if op not in rng:
        raise ValueError("unsupported operator %s" % op)
    return "@%s:%s" % (f, rng[op])


def translate(sql):
    p = P(_toks(sql))
    p.take("SELECT")
    count, fields = False, []
    if p.peek() == "COUNT":
        p.take(); p.take("("); p.take("*"); p.take(")"); count = True
    elif p.peek() == "*":
        p.take()
    else:
        fields.append(p.ident())
        while p.peek() == ",":
            p.take(); fields.append(p.ident())
    p.take("FROM")
    idx = p.ident()
    conds = []
    if p.peek() == "WHERE":
        p.take(); conds.append(_cond(p))
        while p.peek() == "AND":
            p.take(); conds.append(_cond(p))
    q = " ".join(conds) or "*"
    if count:
        if p.peek() is not None:
            raise ValueError("COUNT takes no ORDER/LIMIT")
        return ["FT.SEARCH", idx, q, "LIMIT", "0", "0"]
    cmd = ["FT.SEARCH", idx, q]
    if fields:
        cmd += ["RETURN", str(len(fields))] + fields
    if p.peek() == "ORDER":
        p.take(); p.take("BY"); f = p.ident()
        d = p.take().upper() if p.peek() in ("ASC", "DESC") else "ASC"
        cmd += ["SORTBY", f, d]
    if p.peek() == "LIMIT":
        p.take(); n = p.num(); off = "0"
        if p.peek() == "OFFSET":
            p.take(); off = p.num()
        cmd += ["LIMIT", off, n]
    if p.peek() is not None:
        raise ValueError("unexpected %s" % p.peek())
    return cmd
