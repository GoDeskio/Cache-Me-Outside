"""Builds the Cache Me Outside Grafana dashboard (deploy/helm/cache-me-outside/dashboards/cmo-overview.json).

The panels read the metrics the optional exporter already in the Helm chart
publishes (metrics.exporter.enabled). Edit the panel list here, then run:
    python3 tools/grafana/build_dashboard.py > deploy/helm/cache-me-outside/dashboards/cmo-overview.json
Standard library only.
"""
import json
import sys

SEL = '{namespace=~"$namespace", instance=~"$instance"}'

# (title, unit, [(expr, legend)], width)
PANELS = [
    ("Up", "none", [("min(redis_up%s)" % SEL, "up")], 4, "stat"),
    ("Connected clients", "none", [("sum(redis_connected_clients%s)" % SEL, "clients")], 5, "stat"),
    ("Memory used", "bytes", [("sum(redis_memory_used_bytes%s)" % SEL, "used")], 5, "stat"),
    ("Hit rate", "percentunit", [(
        "sum(rate(redis_keyspace_hits_total%s[5m])) / clamp_min(sum(rate(redis_keyspace_hits_total%s[5m])) + sum(rate(redis_keyspace_misses_total%s[5m])), 1e-9)"
        % (SEL, SEL, SEL), "hit rate")], 5, "stat"),
    ("Replicas connected", "none", [("sum(redis_connected_slaves%s)" % SEL, "replicas")], 5, "stat"),
    ("Ops per second", "ops", [("sum by (instance) (rate(redis_commands_processed_total%s[1m]))" % SEL, "{{instance}}")], 12, "timeseries"),
    ("Memory used vs max", "bytes", [
        ("sum by (instance) (redis_memory_used_bytes%s)" % SEL, "used {{instance}}"),
        ("sum by (instance) (redis_memory_max_bytes%s) > 0" % SEL, "max {{instance}}")], 12, "timeseries"),
    ("Hits and misses per second", "ops", [
        ("sum(rate(redis_keyspace_hits_total%s[1m]))" % SEL, "hits"),
        ("sum(rate(redis_keyspace_misses_total%s[1m]))" % SEL, "misses")], 12, "timeseries"),
    ("Evicted and expired keys per second", "ops", [
        ("sum(rate(redis_evicted_keys_total%s[5m]))" % SEL, "evicted"),
        ("sum(rate(redis_expired_keys_total%s[5m]))" % SEL, "expired")], 12, "timeseries"),
    ("Avg command latency (top 5 commands)", "s", [(
        "topk(5, sum by (cmd) (rate(redis_commands_duration_seconds_total%s[5m])) / clamp_min(sum by (cmd) (rate(redis_commands_total%s[5m])), 1e-9))"
        % (SEL, SEL), "{{cmd}}")], 12, "timeseries"),
    ("Network bytes per second", "Bps", [
        ("sum(rate(redis_net_input_bytes_total%s[1m]))" % SEL, "in"),
        ("sum(rate(redis_net_output_bytes_total%s[1m]))" % SEL, "out")], 12, "timeseries"),
    ("Keys per database", "none", [("sum by (db) (redis_db_keys%s)" % SEL, "{{db}}")], 12, "timeseries"),
    ("Replication link up", "none", [("min by (instance) (redis_master_link_up%s)" % SEL, "{{instance}}")], 12, "timeseries"),
]


def var(name, query):
    return {"name": name, "type": "query", "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "query": {"query": query, "refId": name}, "definition": query, "refresh": 2,
            "includeAll": True, "multi": True, "current": {"text": "All", "value": "$__all"}}


def build():
    panels, x, y, h = [], 0, 0, 0
    for i, (title, unit, targets, w, kind) in enumerate(PANELS, 1):
        ph = 4 if kind == "stat" else 8
        if x + w > 24:
            x, y = 0, y + h
        panels.append({
            "id": i, "type": kind, "title": title,
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "gridPos": {"x": x, "y": y, "w": w, "h": ph},
            "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
            "options": {},
            "targets": [{"refId": chr(65 + j), "expr": e, "legendFormat": l}
                        for j, (e, l) in enumerate(targets)],
        })
        x, h = x + w, ph
    return {
        "title": "Cache Me Outside overview", "uid": "cmo-overview", "schemaVersion": 39,
        "tags": ["cache-me-outside"], "timezone": "browser", "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"}, "editable": True, "panels": panels,
        "templating": {"list": [
            {"name": "datasource", "type": "datasource", "query": "prometheus", "current": {}},
            var("namespace", "label_values(redis_up, namespace)"),
            var("instance", 'label_values(redis_up{namespace=~"$namespace"}, instance)'),
        ]},
    }


if __name__ == "__main__":
    json.dump(build(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
