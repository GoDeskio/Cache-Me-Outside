"""Public pages and unauthenticated product routes for the management server.

Scripts and styles are files, so the page does not need script-src 'unsafe-inline'.
The demo token is returned only to a loopback client of a demo process.
"""
import json
import os

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/console": ("console.html", "text/html; charset=utf-8"),
    "/flow": ("flow.html", "text/html; charset=utf-8"),
    "/integrate": ("integrate.html", "text/html; charset=utf-8"),
    "/assets/style.css": ("style.css", "text/css; charset=utf-8"),
    "/assets/site.js": ("site.js", "text/javascript; charset=utf-8"),
    "/assets/console.js": ("console.js", "text/javascript; charset=utf-8"),
    "/assets/flow.js": ("flow.js", "text/javascript; charset=utf-8"),
    "/assets/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
_AGENT = None
_FLOW = None


def _load(name, filename):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _agent():
    global _AGENT
    if _AGENT is None:
        _AGENT = _load("cmo_site_agent", "agent.py")
    return _AGENT


def _flow():
    global _FLOW
    if _FLOW is None:
        import importlib.util
        path = os.path.normpath(os.path.join(HERE, "..", "tools", "flowview", "flow_feed.py"))
        spec = importlib.util.spec_from_file_location("cmo_flow_feed", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _FLOW = mod
    return _FLOW


def manifest():
    path = os.path.normpath(os.path.join(HERE, "..", "integration", "manifest.json"))
    with open(path) as f:
        data = json.load(f)
    return {
        "name": data["name"],
        "version": data["version"],
        "api": data["api"],
        "adopt": "See INTEGRATION.md. Pass the API address and token from the environment.",
    }


def _send_file(handler, filename, ctype):
    with open(os.path.join(ROOT, filename), "rb") as f:
        body = f.read()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Content-Security-Policy", CSP)
    handler.send_header("X-Frame-Options", "DENY")
    handler.end_headers()
    handler.wfile.write(body)


def _sample(mgr):
    src = getattr(mgr, "flow_source", None)
    if src is None:
        addr = None if getattr(mgr, "demo", False) else mgr.store.upstream
        src = _flow().Source(addr)
        mgr.flow_source = src
    body = src.sample()
    if getattr(mgr, "demo", False):
        body = dict(body, source="demo")
    return body


def try_public(handler, mgr, token, method):
    path = handler.path.split("?")[0]
    if method == "GET" and path in PAGES:
        filename, ctype = PAGES[path]
        _send_file(handler, filename, ctype)
        return True
    if method != "GET":
        return False
    if path == "/v1/integration":
        handler._send(200, manifest())
        return True
    if path == "/v1/flow":
        try:
            handler._send(200, _sample(mgr))
        except Exception:
            handler._send(503, {"error": "feed unavailable"})
        return True
    if path == "/v1/demo":
        loopback = handler.client_address[0] in ("127.0.0.1", "::1")
        if not getattr(mgr, "demo", False) or not loopback:
            handler._send(404, {"error": "not found"})
        else:
            handler._send(200, {"demo": True, "token": token})
        return True
    return False


def agent_run(mgr, message):
    return _agent().run(mgr, message)
