"""MCP server that lets AI agents run Cache Me Outside (plan #129).

These tools take real actions through the management API (#23). The data-plane
key tools are in tools/mcp (#11).

  CMO_API=http://127.0.0.1:8088 CMO_ADMIN_TOKEN=... python3 cmo_ops_mcp.py

Stdio JSON-RPC (MCP 2024-11-05). Destructive tools (delete, rotate) need
"confirm": "<database name>" in their arguments, so an agent cannot fire them by
accident. Every action is appended to CMO_AGENT_AUDIT (JSONL) when that is set.
The admin token is never echoed back.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

NAME = {"type": "string", "pattern": "^[a-z][a-z0-9-]{1,30}$"}
LIM = {"max_conns": {"type": "integer", "minimum": 1}, "ops_per_sec": {"type": "integer", "minimum": 1},
       "bytes_per_sec": {"type": "integer", "minimum": 1}}


def _s(props, req):
    return {"type": "object", "properties": props, "required": req, "additionalProperties": False}


TOOLS = [
    {"name": "db_list", "description": "List all cache databases.", "inputSchema": _s({}, [])},
    {"name": "db_get", "description": "Show one database: port, limits, status.", "inputSchema": _s({"name": NAME}, ["name"])},
    {"name": "db_create", "description": "Create a database with optional limits. Returns its password once.",
     "inputSchema": _s({"name": NAME, "port": {"type": "integer"}, **LIM}, ["name"])},
    {"name": "db_set_limits", "description": "Change connection, ops/s or bytes/s limits (scale up or down).",
     "inputSchema": _s({"name": NAME, **LIM}, ["name"])},
    {"name": "db_rotate_password", "description": "Issue a new password. Destructive: set confirm to the database name.",
     "inputSchema": _s({"name": NAME, "confirm": {"type": "string"}}, ["name", "confirm"])},
    {"name": "db_delete", "description": "Delete a database and its data. Destructive: set confirm to the database name.",
     "inputSchema": _s({"name": NAME, "confirm": {"type": "string"}}, ["name", "confirm"])},
]
DESTRUCTIVE = {"db_rotate_password", "db_delete"}


class Api:
    def __init__(self, base, token, timeout=15):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def __call__(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.load(e)
            except ValueError:
                return e.code, {"error": e.reason}


class Server:
    def __init__(self, api, audit_path=None):
        self.api, self.audit = api, audit_path

    def _log(self, tool, args, status):
        if self.audit:
            with open(self.audit, "a") as f:
                f.write(json.dumps({"ts": time.time(), "tool": tool, "args": args, "status": status}) + "\n")

    def run(self, name, a):
        if name not in {t["name"] for t in TOOLS}:
            raise ValueError("unknown tool " + str(name))
        if name in DESTRUCTIVE and a.get("confirm") != a.get("name"):
            raise ValueError("refused: set confirm to the exact database name")
        lim = {k: a[k] for k in LIM if k in a}
        n = a.get("name", "")
        if name == "db_list":
            st, r = self.api("GET", "/v1/databases")
        elif name == "db_get":
            st, r = self.api("GET", "/v1/databases/" + n)
        elif name == "db_create":
            body = {"name": n, **lim}
            if "port" in a:
                body["port"] = a["port"]
            st, r = self.api("POST", "/v1/databases", body)
        elif name == "db_set_limits":
            if not lim:
                raise ValueError("give at least one limit")
            st, r = self.api("PATCH", "/v1/databases/" + n, lim)
        elif name == "db_rotate_password":
            st, r = self.api("POST", "/v1/databases/%s/rotate-password" % n, {})
        else:
            st, r = self.api("DELETE", "/v1/databases/" + n)
        self._log(name, {k: v for k, v in a.items() if k != "confirm"}, st)
        if st >= 300:
            raise RuntimeError("API %s: %s" % (st, r.get("error", r)))
        return r

    def handle(self, msg):
        mid, m, p = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:
            return None
        if m == "initialize":
            res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                   "serverInfo": {"name": "cache-me-outside-ops", "version": "0.1.0"}}
        elif m == "tools/list":
            res = {"tools": TOOLS}
        elif m == "tools/call":
            try:
                data = self.run(p.get("name"), p.get("arguments") or {})
                res = {"content": [{"type": "text", "text": json.dumps(data)}]}
            except Exception as e:  # noqa: BLE001 - reported to the agent as a tool error
                res = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}


def main():
    s = Server(Api(os.environ.get("CMO_API", "http://127.0.0.1:8088"), os.environ.get("CMO_ADMIN_TOKEN", "")),
               os.environ.get("CMO_AGENT_AUDIT"))
    for line in sys.stdin:
        if line.strip():
            out = s.handle(json.loads(line))
            if out:
                sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()


if __name__ == "__main__":
    main()
