"""Generate Grafana dashboards for CMO metrics (plan #131).

The OTLP push from tools/otlp (#40) goes to Prometheus's OTLP receiver
(--web.enable-otlp-receiver), which turns `cmo.keyspace.hits` into
`cmo_keyspace_hits` (counters get a `_total` suffix). This writes provisioned
dashboard JSON under deploy/grafana/dashboards.
"""
import json
import os
import sys

DS = {"type": "prometheus", "uid": "cmo-prom"}

# (title, expr, unit, panel type)
OVERVIEW = [
    ("Ops per second", 'sum by (db) (cmo_ops_rate)', "ops", "timeseries"),
    ("Hit ratio", 'sum(rate(cmo_keyspace_hits_total[5m])) / clamp_min(sum(rate(cmo_keyspace_hits_total[5m])) + sum(rate(cmo_keyspace_misses_total[5m])), 1)', "percentunit", "stat"),
    ("Hits vs misses", 'sum by (db) (rate(cmo_keyspace_hits_total[5m])) or sum by (db) (rate(cmo_keyspace_misses_total[5m]))', "ops", "timeseries"),
    ("Memory used", 'sum by (db) (cmo_memory_used)', "bytes", "timeseries"),
    ("Memory used / max", 'sum by (db) (cmo_memory_used) / clamp_min(sum by (db) (cmo_memory_max), 1)', "percentunit", "gauge"),
    ("Fragmentation", 'max by (db) (cmo_memory_fragmentation)', "none", "timeseries"),
    ("Clients connected", 'sum by (db) (cmo_clients_connected)', "none", "timeseries"),
    ("Rejected connections", 'sum by (db) (rate(cmo_connections_rejected_total[5m]))', "ops", "timeseries"),
    ("Evicted keys", 'sum by (db) (rate(cmo_keys_evicted_total[5m]))', "ops", "timeseries"),
    ("Expired keys", 'sum by (db) (rate(cmo_keys_expired_total[5m]))', "ops", "timeseries"),
    ("Commands", 'sum by (db) (rate(cmo_commands_total[5m]))', "ops", "timeseries"),
    ("Replicas connected", 'min by (db) (cmo_replicas_connected)', "none", "stat"),
]

TENANT = [
    ("Tenant ops", 'cmo_ops_rate{db="$db"}', "ops", "timeseries"),
    ("Tenant hit ratio", 'rate(cmo_keyspace_hits_total{db="$db"}[5m]) / clamp_min(rate(cmo_keyspace_hits_total{db="$db"}[5m]) + rate(cmo_keyspace_misses_total{db="$db"}[5m]), 1)', "percentunit", "timeseries"),
    ("Tenant memory", 'cmo_memory_used{db="$db"}', "bytes", "timeseries"),
    ("Tenant evictions", 'rate(cmo_keys_evicted_total{db="$db"}[5m])', "ops", "timeseries"),
]


def panels(spec):
    out = []
    for i, (title, expr, unit, typ) in enumerate(spec):
        out.append({
            "id": i + 1, "type": typ, "title": title, "datasource": DS,
            "gridPos": {"h": 8, "w": 12, "x": (i % 2) * 12, "y": (i // 2) * 8},
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr}],
        })
    return out


def dashboard(uid, title, spec, tenant_var=False):
    d = {"uid": uid, "title": title, "schemaVersion": 39, "tags": ["cache-me-outside"],
         "time": {"from": "now-6h", "to": "now"}, "refresh": "30s", "panels": panels(spec),
         "templating": {"list": []}}
    if tenant_var:
        d["templating"]["list"].append({"name": "db", "type": "query", "datasource": DS,
                                        "query": "label_values(cmo_ops_rate, db)", "refresh": 2})
    return d


def build():
    return {"cmo-overview.json": dashboard("cmo-overview", "Cache Me Outside: overview", OVERVIEW),
            "cmo-tenant.json": dashboard("cmo-tenant", "Cache Me Outside: tenant", TENANT, True)}


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    for name, d in build().items():
        with open(os.path.join(outdir, name), "w") as f:
            json.dump(d, f, indent=2)
            f.write("\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "../../deploy/grafana/dashboards"))
