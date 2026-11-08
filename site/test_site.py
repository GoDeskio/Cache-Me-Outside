import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools", "mgmt"))

import agent
import cmo_mgmt as mgmt
import server


def start(argv):
    addr, mgr, token, _args = server.build(argv)
    httpd = ThreadingHTTPServer(addr, mgmt.make_handler(mgr, token))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, token, mgr


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, dict(response.headers), response.read()


class Site(unittest.TestCase):
    def setUp(self):
        self.httpd, self.token, self.mgr = start(["--demo", "--listen", "127.0.0.1:0"])
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def call(self, method, path, body=None, token=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Authorization": "Bearer " + (token if token is not None else self.token),
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_pages_and_csp(self):
        status, headers, body = get(self.base + "/")
        html = body.decode()
        self.assertEqual(status, 200)
        self.assertIn('id="hero"', html)
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])
        self.assertNotIn("innerHTML", html)
        self.assertIn("GitGoat", html)
        self.assertNotIn("GitGoat", html.split('id="hero"')[1].split("</section>")[0])
        console = get(self.base + "/console")[2].decode()
        self.assertIn("Create database", console)
        self.assertNotIn('pattern="[a-z][a-z0-9-]', console)

    def test_demo_token_and_database_roundtrip(self):
        demo = self.call("GET", "/v1/demo", token="ignored")
        # /v1/demo is public. The helper still sends a token; that is fine.
        status, payload = demo
        self.assertEqual(status, 200)
        self.assertEqual(payload["token"], self.token)
        created = self.call("POST", "/v1/databases", {"name": "acme"})[1]
        self.assertEqual(created["sample_key"], "acme:welcome")
        scanned = self.call("GET", "/v1/databases/acme/keys?match=w*")[1]
        self.assertEqual(scanned["keys"], ["acme:welcome"])
        shown = self.call("GET", "/v1/databases/acme/keys?key=acme%3Awelcome")[1]
        self.assertEqual(shown["value"], "hello from Cache Me Outside")
        self.assertEqual(self.call("GET", "/v1/databases/acme/keys?key=other%3Ax")[0], 403)
        self.assertEqual(self.call("PATCH", "/v1/databases/acme", {"ops_per_sec": 25})[1]["ops_per_sec"], 25)
        self.assertEqual(self.call("DELETE", "/v1/databases/acme")[0], 200)

    def test_agent_creates_without_a_model(self):
        os.environ.pop("OLLAMA_BASE_URL", None)
        status, payload = self.call("POST", "/v1/agent", {"message": "create database beta"})
        self.assertEqual(status, 200)
        self.assertIn("beta", payload["reply"])
        self.assertIn("Password", payload["reply"])
        names = [row["name"] for row in self.call("GET", "/v1/databases")[1]["databases"]]
        self.assertIn("beta", names)
        opened = self.call("POST", "/v1/agent", {"message": "open flow"})[1]
        self.assertEqual(opened["actions"][0]["href"], "/flow")
        refused = self.call("POST", "/v1/agent", {"message": "write a poem about caches"})[1]
        self.assertIn("OLLAMA_BASE_URL", refused["reply"])
        self.assertEqual(refused["actions"], [])

    def test_flow_is_labeled_demo(self):
        status, payload = self.call("GET", "/v1/flow", token="ignored")
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "demo")
        self.assertGreater(payload["req"], 0)
        version = self.call("GET", "/v1/integration", token="ignored")[1]
        self.assertEqual(version["version"], "1.0.0")


class Agent(unittest.TestCase):
    def test_model_cannot_request_a_shell(self):
        class Store:
            def __init__(self):
                self.names = []
            def list(self):
                return [{"name": n} for n in self.names]
            def create(self, body):
                self.names.append(body["name"])
                return {"name": body["name"], "port": 7001, "password": "pw"}
        store = Store()
        reply = agent.run(store, "do something unusual", ask=lambda _m: '{"action":"shell","cmd":"id"}')
        self.assertEqual(store.names, [])
        self.assertIn("something I can do", reply["reply"])
        made = agent.run(store, "please make one", ask=lambda _m: '{"action":"create","name":"from-model"}')
        self.assertEqual(store.names, ["from-model"])
        self.assertIn("from-model", made["reply"])

    def test_bad_ollama_url_does_not_run_a_command(self):
        os.environ["OLLAMA_BASE_URL"] = "file:///tmp/not-a-server"
        try:
            reply = agent.run(object(), "tell me anything at all")
        finally:
            os.environ.pop("OLLAMA_BASE_URL", None)
        self.assertIn("did not answer", reply["reply"])

    def test_ollama_say_and_redirect_refused(self):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(n)
                if "bounce" in self.path:
                    self.send_response(302)
                    self.send_header("Location", "http://127.0.0.1:9/nope")
                    self.end_headers()
                    return
                body = json.dumps({"message": {"content": '{"action":"say","text":"from the local model"}'}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            said = agent.run(object(), "tell me anything at all")
            self.assertEqual(said["reply"], "from the local model")
            os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:%d/bounce" % httpd.server_address[1]
            bounced = agent.run(object(), "tell me anything at all")
            self.assertIn("did not answer", bounced["reply"])
        finally:
            os.environ.pop("OLLAMA_BASE_URL", None)
            httpd.shutdown()
            httpd.server_close()


class Listen(unittest.TestCase):
    def test_demo_refuses_a_public_address(self):
        with self.assertRaises(SystemExit):
            server.build(["--demo", "--listen", "0.0.0.0:8088"])

    def test_real_mode_hides_the_demo_token(self):
        import tempfile
        previous = os.environ.get("CMO_ADMIN_TOKEN")
        os.environ["CMO_ADMIN_TOKEN"] = "t" * 32
        directory = tempfile.mkdtemp()
        try:
            httpd, _token, mgr = start(["--config", os.path.join(directory, "p.json"), "--listen", "127.0.0.1:0"])
            self.assertFalse(getattr(mgr, "demo", False))
            base = "http://127.0.0.1:%d" % httpd.server_address[1]
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "/v1/demo")
            self.assertEqual(caught.exception.code, 404)
            httpd.shutdown()
            httpd.server_close()
        finally:
            if previous is None:
                os.environ.pop("CMO_ADMIN_TOKEN", None)
            else:
                os.environ["CMO_ADMIN_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
