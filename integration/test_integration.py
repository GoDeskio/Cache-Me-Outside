import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cache_me_outside
import sidecar
import updater

ASSET = updater.ASSET


def archive(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as handle:
        for name, data in files.items():
            if isinstance(data, tuple):
                info, payload = data
            else:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                payload = data
            handle.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


class Release(BaseHTTPRequestHandler):
    blob = b""
    sums = b""
    releases = []

    def do_GET(self):
        if self.path.startswith("/releases"):
            body = json.dumps(self.releases).encode()
        elif self.path == "/blob":
            body = type(self).blob
        elif self.path == "/sums":
            body = type(self).sums
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


class Updater(unittest.TestCase):
    def setUp(self):
        self.dest = tempfile.mkdtemp()
        with open(os.path.join(self.dest, "manifest.json"), "w") as handle:
            json.dump({"version": "1.0.0"}, handle)
        manifest = json.dumps({"name": "cache-me-outside", "version": "1.1.0", "api": "v1"}).encode()
        self.blob = archive({"pkg/manifest.json": manifest, "pkg/cache_me_outside.py": b"print(1)\n"})
        Release.blob = self.blob
        Release.sums = (hashlib.sha256(self.blob).hexdigest() + "  " + ASSET + "\n").encode()
        Release.releases = [{
            "tag_name": "cmo-integration-v1.1.0",
            "assets": [
                {"name": ASSET, "browser_download_url": ""},
                {"name": "SHA256SUMS", "browser_download_url": ""},
            ],
        }]
        self.httpd = serve(Release)
        base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        Release.releases[0]["assets"][0]["browser_download_url"] = base + "/blob"
        Release.releases[0]["assets"][1]["browser_download_url"] = base + "/sums"
        self.api = base + "/releases"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_apply_checks_the_hash_and_rejects_traversal(self):
        result = updater.apply(self.api, self.dest)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(updater.local_version(self.dest), "1.1.0")
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "cache_me_outside.py")))
        Release.sums = (b"0" * 64 + b"  " + ASSET.encode() + b"\n")
        with open(os.path.join(self.dest, "manifest.json"), "w") as handle:
            json.dump({"version": "1.0.0"}, handle)
        with self.assertRaises(ValueError):
            updater.apply(self.api, self.dest)
        self.assertEqual(updater.local_version(self.dest), "1.0.0")
        bad = archive({"../manifest.json": b"{}"})
        with self.assertRaises(ValueError):
            updater.unpack(bad)
        link = tarfile.TarInfo("manifest.json")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        with self.assertRaises(ValueError):
            updater.unpack(archive({"manifest.json": (link, b"")}))

    def test_no_release_is_not_a_failure(self):
        Release.releases = []
        found = updater.check(self.api, self.dest)
        self.assertEqual(found["status"], "none")
        self.assertEqual(found["version"], "1.0.0")

    def test_file_url_is_refused(self):
        found = updater.check("file:///tmp/releases", self.dest)
        self.assertEqual(found["status"], "unreachable")


class ClientAndSidecar(unittest.TestCase):
    def test_package_version_and_node_client(self):
        self.assertEqual(cache_me_outside.version(), "1.0.0")
        with self.assertRaises(ValueError):
            cache_me_outside.Client("http://127.0.0.1:9", "")
        script = (
            "const c=require('./cache-me-outside.js');"
            "if(c.version!=='1.0.0') process.exit(1);"
            "try{c.attach({});process.exit(1)}catch(e){}"
        )
        subprocess.check_call(["node", "-e", script], cwd=HERE)

    def test_prefix_is_enforced_before_connect(self):
        with self.assertRaises(ValueError):
            sidecar.cache_call("redis://127.0.0.1:1", "app:", ["GET", "other:x"])
        with self.assertRaises(ValueError):
            sidecar.cache_call("redis://127.0.0.1:1", "app:", ["FLUSHALL", "app:x"])
        with self.assertRaises(ValueError):
            sidecar.cache_call("rediss://127.0.0.1:1", "app:", ["GET", "app:x"])

    def test_get_roundtrip_and_health(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)

        def once():
            conn, _addr = sock.accept()
            conn.recv(1024)
            conn.sendall(b"$5\r\nhello\r\n")
            conn.close()

        threading.Thread(target=once, daemon=True).start()
        port = sock.getsockname()[1]
        self.assertEqual(sidecar.cache_call("redis://127.0.0.1:%d" % port, "app:", ["GET", "app:k"]), b"hello")
        sock.close()
        httpd = serve(sidecar.make_handler(None, "", ""))
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/health" % httpd.server_address[1]) as response:
                self.assertEqual(json.load(response)["version"], "1.0.0")
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/cache/get" % httpd.server_address[1],
                data=b'{"key":"app:k"}', headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 503)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_sidecar_refuses_a_public_bind(self):
        with self.assertRaises(SystemExit):
            sidecar.main(["--listen", "0.0.0.0:8099"])


if __name__ == "__main__":
    unittest.main()
