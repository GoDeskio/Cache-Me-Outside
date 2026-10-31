#!/usr/bin/env python3
"""Write-through / write-behind to databases (plan item 67).

Apps write to the cache and XADD a change record to a stream
(`cmo:wb:<table>` with fields op=upsert|delete, id, data=<json>). This worker
reads the stream with a consumer group, applies batches to a Sink in one DB
transaction, and acks only after commit (at-least-once; sinks are idempotent
upserts). Records that fail `max_tries` times go to a dead-letter stream.

Sinks: SqliteSink here (and for tests); PostgresSink uses the same SQL with
psycopg if installed. Mongo is a follow-up.
`write_through(stream, sink, rec)` applies synchronously for callers that need it.

`Stream` is an interface over XREADGROUP/XACK/XADD so the worker can be tested
without a server.
"""
import json
import re
import time

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class SqliteSink:
    def __init__(self, conn, table):
        if not IDENT.match(table):
            raise ValueError("bad table name")
        self.c, self.t = conn, table
        self.c.execute('CREATE TABLE IF NOT EXISTS "%s" (id TEXT PRIMARY KEY, data TEXT NOT NULL)' % table)

    def apply(self, records):
        with self.c:
            for r in records:
                if r["op"] == "upsert":
                    json.loads(r["data"])  # reject non-JSON before it lands
                    self.c.execute('INSERT INTO "%s"(id, data) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data' % self.t,
                                   (r["id"], r["data"]))
                elif r["op"] == "delete":
                    self.c.execute('DELETE FROM "%s" WHERE id=?' % self.t, (r["id"],))
                else:
                    raise ValueError("unknown op %r" % r["op"])


class PostgresSink(SqliteSink):
    def __init__(self, dsn, table):
        import psycopg  # optional dependency
        if not IDENT.match(table):
            raise ValueError("bad table name")
        self.c, self.t = psycopg.connect(dsn), table
        with self.c:
            self.c.execute('CREATE TABLE IF NOT EXISTS "%s" (id TEXT PRIMARY KEY, data JSONB NOT NULL)' % table)

    def apply(self, records):
        with self.c.transaction():
            for r in records:
                if r["op"] == "upsert":
                    self.c.execute('INSERT INTO "%s"(id, data) VALUES(%%s, %%s) ON CONFLICT(id) DO UPDATE SET data=excluded.data' % self.t,
                                   (r["id"], r["data"]))
                elif r["op"] == "delete":
                    self.c.execute('DELETE FROM "%s" WHERE id=%%s' % self.t, (r["id"],))
                else:
                    raise ValueError("unknown op %r" % r["op"])


class Worker:
    def __init__(self, stream, sink, batch=100, max_tries=5):
        self.s, self.sink, self.batch, self.max_tries = stream, sink, batch, max_tries
        self.tries = {}

    def step(self):
        """Read one batch and apply it. Returns number of records committed."""
        msgs = self.s.read(self.batch)  # [(msg_id, fields)]
        if not msgs:
            return 0
        try:
            self.sink.apply([f for _, f in msgs])
            self.s.ack([m for m, _ in msgs])
            return len(msgs)
        except Exception:
            # Batch failed: retry records one by one so one bad record can't block the rest.
            done = 0
            for mid, f in msgs:
                try:
                    self.sink.apply([f])
                    self.s.ack([mid])
                    done += 1
                    self.tries.pop(mid, None)
                except Exception as e:
                    self.tries[mid] = self.tries.get(mid, 0) + 1
                    if self.tries[mid] >= self.max_tries:
                        self.s.dead_letter(mid, f, str(e))
                        self.s.ack([mid])
                        self.tries.pop(mid)
            return done

    def run(self, idle=0.5):
        while True:
            if not self.step():
                time.sleep(idle)


def write_through(sink, rec):
    sink.apply([rec])
