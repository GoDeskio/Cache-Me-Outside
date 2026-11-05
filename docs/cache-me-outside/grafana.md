# Grafana dashboard

`deploy/helm/cache-me-outside/dashboards/cmo-overview.json` is the "Cache Me Outside overview" dashboard. It shows:
- whether each node is up
- client count
- memory used, and memory used vs. max
- hit rate, plus hits and misses
- ops per second
- evicted and expired keys
- average latency of the top 5 commands
- network traffic
- keys per database
- replica count and replication link status

You can filter by datasource, namespace and instance.

It reads the metrics from the chart's optional exporter, so set `metrics.exporter.enabled=true`.

- **Kubernetes:** set `metrics.grafanaDashboard.enabled=true`. This creates a ConfigMap labelled `grafana_dashboard: "1"`, which Grafana's dashboard sidecar picks up.
- **Anywhere else:** in Grafana, go to Dashboards → Import and upload the JSON.

To change the dashboard, edit `tools/grafana/build_dashboard.py`, then run:

    python3 tools/grafana/build_dashboard.py > deploy/helm/cache-me-outside/dashboards/cmo-overview.json

A test fails if the checked-in JSON is out of date.
