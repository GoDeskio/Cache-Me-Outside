#!/usr/bin/env python3
"""Push Cache-Me-Outside metrics to any OpenTelemetry collector (plan item 53).

Reads INFO from each node and POSTs OTLP/HTTP JSON to <endpoint>/v1/metrics,
which the OTel Collector, Datadog Agent (OTLP intake), Grafana Alloy and
others accept. Stdlib only.

  CMO_NODES=127.0.0.1:6379 CMO_USER=metrics CMO_PASS_FILE=/run/secrets/m \
  OTLP_ENDPOINT=http://collector:4318 python3 otlp_export.py --every 15
"""
import argparse
import json
import os
import socket
import time
import urllib.request

GAUGES = {
    "used_memory": ("cmo.memory.used", "By"),
    "maxmemory": ("cmo.memory.max", "By"),
    "connected_clients": ("cmo.clients.connected", "{client}"),
    "instantaneous_ops_per_sec": ("cmo.ops.rate", "{op}/s"),
    "mem_fragmentation_ratio": ("cmo.memory.fragmentation", "1"),
    "connected_slaves": ("cmo.replicas.connected", "{replica}"),
}
COUNTERS = {
    "keyspace_hits": ("cmo.keyspace.hits", "{hit}"),
    "keyspace_misses": ("cmo.keyspace.misses", "{miss}"),
    "evicted_keys": ("cmo.keys.evicted", "{key}"),
    "expired_keys": ("cmo.keys.expired", "{key}"),
    "total_commands_processed": ("cmo.commands", "{command}"),
    "rejected_connections": ("cmo.connections.rejected", "{connection}"),
}


def parse_info(text):
    out = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            out[k] = v.strip()
    return out


def fetch_info(node, user=None, password=None, timeout=3):
    host, port = node.rsplit(":", 1)
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        f = s.makefile("rb")
        def cmd(*a):
            s.sendall(b"*%d\r\n" % len(a) + b"".join(b"$%d\r\n%s\r\n" % (len(x.encode()), x.encode()) for x in a))
            line = f.readline()
            if line.startswith(b"-"):
                raise RuntimeError(line[1:].strip().decode())
            if line.startswith(b"$"):
                n = int(line[1:])
                return f.read(n + 2)[:-2].decode()
            return line.strip().decode()
        if password:
            cmd("AUTH", user or "default", password)
        return cmd("INFO")


def to_otlp(samples, now_ns, start_ns):
    """samples: {node: info-dict}. Returns an OTLP ExportMetricsServiceRequest dict."""
    metrics = {}
    for node, info in samples.items():
        attrs = [{"key": "cmo.node", "value": {"stringValue": node}},
                 {"key": "cmo.role", "value": {"stringValue": info.get("role", "unknown")}}]
        for table, kind in ((GAUGES, "gauge"), (COUNTERS, "sum")):
            for key, (name, unit) in table.items():
                if key not in info:
                    continue
                try:
                    v = float(info[key])
                except ValueError:
                    continue
                pt = {"attributes": attrs, "timeUnixNano": str(now_ns), "asDouble": v}
                if kind == "sum":
                    pt["startTimeUnixNano"] = str(start_ns)
                m = metrics.setdefault(name, {"name": name, "unit": unit, kind: {"dataPoints": []}})
                m[kind]["dataPoints"].append(pt)
        h, ms = float(info.get("keyspace_hits", 0)), float(info.get("keyspace_misses", 0))
        if h + ms:
            m = metrics.setdefault("cmo.keyspace.hit_ratio", {"name": "cmo.keyspace.hit_ratio", "unit": "1", "gauge": {"dataPoints": []}})
            m["gauge"]["dataPoints"].append({"attributes": attrs, "timeUnixNano": str(now_ns), "asDouble": h / (h + ms)})
    for m in metrics.values():
        if "sum" in m:
            m["sum"].update({"aggregationTemporality": 2, "isMonotonic": True})
    return {"resourceMetrics": [{
        "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "cache-me-outside"}}]},
        "scopeMetrics": [{"scope": {"name": "cmo.otlp_export"}, "metrics": list(metrics.values())}],
    }]}


def push(endpoint, body, headers=None, timeout=5):
    req = urllib.request.Request(endpoint.rstrip("/") + "/v1/metrics", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=0, help="seconds between pushes; 0 = once")
    a = ap.parse_args()
    nodes = os.environ.get("CMO_NODES", "127.0.0.1:6379").split(",")
    pw = None
    if os.environ.get("CMO_PASS_FILE"):
        pw = open(os.environ["CMO_PASS_FILE"]).read().strip()
    hdrs = {}
    if os.environ.get("OTLP_HEADERS"):  # k=v,k=v (e.g. an API key header)
        hdrs = dict(kv.split("=", 1) for kv in os.environ["OTLP_HEADERS"].split(","))
    start = time.time_ns()
    while True:
        samples = {}
        for n in nodes:
            try:
                samples[n] = parse_info(fetch_info(n, os.environ.get("CMO_USER"), pw))
            except (OSError, RuntimeError) as e:
                print("skip %s: %s" % (n, e))
        if samples:
            push(os.environ.get("OTLP_ENDPOINT", "http://127.0.0.1:4318"), to_otlp(samples, time.time_ns(), start), hdrs)
        if not a.every:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
