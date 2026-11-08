"""Small client for the Cache Me Outside management API. Standard library only."""
import json
import os
import urllib.error
import urllib.request

_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")


def version():
    with open(_MANIFEST) as handle:
        return json.load(handle)["version"]


class Client:
    def __init__(self, api, token, timeout=15):
        if not api or not str(api).startswith(("http://", "https://")):
            raise ValueError("api must be an http or https URL")
        if not token or not isinstance(token, str):
            raise ValueError("token is required")
        self.api = api.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.api + path, data=data, method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            payload = json.load(exc)
            raise RuntimeError(payload.get("error") or str(exc.code)) from None

    def list_databases(self):
        return self._call("GET", "/v1/databases")["databases"]

    def create_database(self, name, **limits):
        body = {"name": name}
        body.update(limits)
        return self._call("POST", "/v1/databases", body)

    def get_database(self, name):
        return self._call("GET", "/v1/databases/" + name)

    def update_limits(self, name, **limits):
        return self._call("PATCH", "/v1/databases/" + name, limits)

    def rotate_password(self, name):
        return self._call("POST", "/v1/databases/%s/rotate-password" % name, {})

    def delete_database(self, name):
        return self._call("DELETE", "/v1/databases/" + name)

    def scan_keys(self, name, match="*", cursor="0"):
        return self._call("GET", "/v1/databases/%s/keys?cursor=%s&match=%s" % (name, cursor, match))

    def show_key(self, name, key):
        from urllib.parse import quote
        return self._call("GET", "/v1/databases/%s/keys?key=%s" % (name, quote(key, safe="")))
