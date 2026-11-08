"""Deterministic site agent. OLLAMA_BASE_URL is optional and never required.

The planner only recognizes a fixed sentence list. Anything else is sent to a
local Ollama server when that URL is set. The model may only ask for the same
actions the planner can already run. Unknown actions are dropped.
"""
import json
import os
import re
import urllib.request
from urllib.parse import urlsplit

NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
NAV = {"home": "/", "console": "/console", "flow": "/flow", "integrate": "/integrate"}
TOPICS = {
    "tenants": "Each database gets its own port, its own password, and keys that must start with its name.",
    "browser": "The key browser is read-only. It only returns keys under that database's prefix.",
    "flow": "The flow page shows requests, near-cache hits, cache hits, misses, and the database queries those misses become.",
    "warm": "Warm restart can reload a checkpoint after a clean shutdown when RDB and AOF did not. It stays off until it is configured.",
    "hybrid": "Hybrid storage can spill large strings to a flash log. It stays off until it is configured.",
    "ttl": "TTL segments delete keys that expire in the same time bucket. They stay off until configured.",
    "integration": "Other GoDesk apps adopt the integration directory. The token comes from the environment, never from the repository.",
}
HELP = (
    "I can list databases, create database <name>, delete database <name>, "
    "rotate password <name>, set ops for <name> to <number>, browse <name>, "
    "explain tenants, or open home, console, flow, or integrate. "
    "Those run here with no model. Free-form chat uses OLLAMA_BASE_URL and does not call a paid provider."
)
ALLOWED = {"say", "navigate", "list", "create", "delete", "rotate", "limits", "browse", "explain"}
LIMITS = {"ops": "ops_per_sec", "connections": "max_conns", "bytes": "bytes_per_sec"}
SYSTEM = (
    "You control Cache Me Outside. Reply with one JSON object and no other text. "
    'Allowed actions: {"action":"say","text":"..."}, '
    '{"action":"navigate","href":"/"}, {"action":"list"}, '
    '{"action":"create","name":"example"}, {"action":"delete","name":"example"}, '
    '{"action":"rotate","name":"example"}, '
    '{"action":"limits","name":"example","field":"ops_per_sec","value":10}, '
    '{"action":"browse","name":"example"}, {"action":"explain","topic":"tenants"}. '
    "href is one of /, /console, /flow, /integrate. "
    "field is ops_per_sec, max_conns, or bytes_per_sec. "
    "topic is tenants, browser, flow, warm, hybrid, ttl, or integration. "
    "Do not request any other action."
)


def plan(message):
    low = " ".join(message.lower().split())
    if low in ("help", "what can you do", "?"):
        return {"action": "say", "text": HELP}
    m = re.match(r"(?:please )?open (?:the )?(home|console|flow|integrate)(?: page)?$", low)
    if m:
        return {"action": "navigate", "href": NAV[m.group(1)], "text": "Opening %s." % m.group(1)}
    if low in ("list databases", "show databases"):
        return {"action": "list"}
    m = re.match(r"create database ([a-z0-9-]+)$", low)
    if m:
        return {"action": "create", "name": m.group(1)}
    m = re.match(r"delete database ([a-z0-9-]+)$", low)
    if m:
        return {"action": "delete", "name": m.group(1)}
    m = re.match(r"(?:rotate password|new password for) ([a-z0-9-]+)$", low)
    if m:
        return {"action": "rotate", "name": m.group(1)}
    m = re.match(r"set (ops|connections|bytes) for ([a-z0-9-]+) to (\d+)$", low)
    if m:
        return {"action": "limits", "name": m.group(2), "field": LIMITS[m.group(1)], "value": int(m.group(3))}
    m = re.match(r"(?:browse|show keys in) ([a-z0-9-]+)$", low)
    if m:
        return {"action": "browse", "name": m.group(1)}
    m = re.match(r"explain ([a-z]+)$", low)
    if m:
        return {"action": "explain", "topic": m.group(1)}
    return None


def _name(obj):
    name = obj.get("name", "")
    if not isinstance(name, str) or not NAME.match(name):
        raise ValueError("name: 2-31 chars, lowercase letters, digits, dashes, starting with a letter")
    return name


def perform(mgr, obj):
    action = obj.get("action")
    if action == "say":
        text = obj.get("text", "")
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        return {"reply": text[:2000], "actions": []}
    if action == "navigate":
        href = obj.get("href")
        if href not in NAV.values():
            raise ValueError("that page is not on this site")
        return {"reply": obj.get("text") or "Opening that page.", "actions": [{"op": "navigate", "href": href}]}
    if action == "explain":
        topic = obj.get("topic")
        if topic not in TOPICS:
            raise ValueError("I can explain tenants, browser, flow, warm, hybrid, ttl, or integration.")
        return {"reply": TOPICS[topic], "actions": []}
    if action == "list":
        rows = mgr.list()
        names = ", ".join(d["name"] for d in rows) or "none yet"
        return {"reply": "Databases: %s." % names, "actions": [{"op": "refresh"}]}
    if action == "create":
        out = mgr.create({"name": _name(obj)})
        reply = "Database %s is on port %s. Password, shown once: %s." % (out["name"], out["port"], out["password"])
        if out.get("sample_key"):
            reply += " Sample key %s was added for the local demo." % out["sample_key"]
        return {"reply": reply, "actions": [{"op": "refresh"}]}
    if action == "delete":
        out = mgr.delete(_name(obj))
        return {"reply": "Deleted %s. Keys under that prefix were kept." % out["deleted"], "actions": [{"op": "refresh"}]}
    if action == "rotate":
        out = mgr.rotate(_name(obj))
        return {"reply": "New password for %s, shown once: %s." % (out["name"], out["password"]),
                "actions": [{"op": "refresh"}]}
    if action == "limits":
        field = obj.get("field")
        value = obj.get("value")
        if field not in ("ops_per_sec", "max_conns", "bytes_per_sec"):
            raise ValueError("limit must be ops, connections, or bytes")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("limit must be a non-negative integer")
        out = mgr.update(_name(obj), {field: value})
        shown = "unlimited" if out[field] == 0 else str(out[field])
        return {"reply": "%s for %s is now %s." % (field, out["name"], shown), "actions": [{"op": "refresh"}]}
    if action == "browse":
        name = _name(obj)
        found = mgr.keys(name, "/v1/databases/%s/keys" % name)
        keys = found.get("keys") or []
        shown = ", ".join(keys[:20]) or "no keys"
        return {"reply": "Keys in %s: %s." % (name, shown),
                "actions": [{"op": "browse", "name": name}, {"op": "refresh"}]}
    raise ValueError("I can't do that")


def parse_model(raw):
    if not isinstance(raw, str):
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("action") not in ALLOWED:
        return None
    return obj


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirect refused")


def ask_ollama(message):
    base = os.environ.get("OLLAMA_BASE_URL", "").strip().rstrip("/")
    parts = urlsplit(base)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("OLLAMA_BASE_URL must be an http or https URL without a user")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2")
    if not re.match(r"^[A-Za-z0-9._:-]{1,80}$", model):
        raise ValueError("OLLAMA_MODEL is not a model name")
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": message},
        ],
    }).encode()
    opener = urllib.request.build_opener(_RefuseRedirect)
    req = urllib.request.Request(base + "/api/chat", data=payload, headers={"Content-Type": "application/json"})
    with opener.open(req, timeout=8) as r:
        data = json.loads(r.read(65536).decode())
    return data.get("message", {}).get("content", "")


def run(mgr, message, ask=None):
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    message = message.strip()
    if not message or len(message) > 500:
        raise ValueError("message must be 1-500 characters")
    planned = plan(message)
    if planned is None:
        if ask is None and not os.environ.get("OLLAMA_BASE_URL"):
            return {"reply": HELP, "actions": []}
        try:
            raw = (ask or ask_ollama)(message)
        except Exception:
            return {"reply": "The local model did not answer. " + HELP, "actions": []}
        planned = parse_model(raw)
        if planned is None:
            return {"reply": "The local model did not ask for something I can do. " + HELP, "actions": []}
    return perform(mgr, planned)
