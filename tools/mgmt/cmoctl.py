"""cmoctl: command-line client for the management API (REA plan item 64).

  export CMO_API=http://127.0.0.1:8088 CMO_ADMIN_TOKEN=...
  cmoctl.py list
  cmoctl.py create acme [--ops-per-sec 1000] [--max-conns 50] [--bytes-per-sec N] [--port 7001]
  cmoctl.py get acme
  cmoctl.py limits acme --ops-per-sec 2000
  cmoctl.py rotate acme
  cmoctl.py delete acme --yes
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def call(method, path, body=None, base=None, token=None):
    base = (base or os.environ.get("CMO_API", "http://127.0.0.1:8088")).rstrip("/")
    token = token or os.environ.get("CMO_ADMIN_TOKEN", "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="cmoctl")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for c in ("get", "rotate"):
        sub.add_parser(c).add_argument("name")
    d = sub.add_parser("delete"); d.add_argument("name"); d.add_argument("--yes", action="store_true")
    for c in ("create", "limits"):
        p = sub.add_parser(c); p.add_argument("name")
        p.add_argument("--max-conns", type=int); p.add_argument("--ops-per-sec", type=int)
        p.add_argument("--bytes-per-sec", type=int)
        if c == "create":
            p.add_argument("--port", type=int)
    a = ap.parse_args(argv)
    lim = {k: getattr(a, k) for k in ("max_conns", "ops_per_sec", "bytes_per_sec")
           if getattr(a, k, None) is not None}
    if a.cmd == "list":
        st, r = call("GET", "/v1/databases")
    elif a.cmd == "get":
        st, r = call("GET", "/v1/databases/" + a.name)
    elif a.cmd == "rotate":
        st, r = call("POST", "/v1/databases/%s/rotate-password" % a.name, {})
    elif a.cmd == "delete":
        if not a.yes:
            print("refusing without --yes", file=sys.stderr)
            return 2
        st, r = call("DELETE", "/v1/databases/" + a.name)
    elif a.cmd == "create":
        body = {"name": a.name, **lim}
        if a.port:
            body["port"] = a.port
        st, r = call("POST", "/v1/databases", body)
    else:
        st, r = call("PATCH", "/v1/databases/" + a.name, lim)
    json.dump(r, out, indent=2)
    out.write("\n")
    return 0 if st < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
