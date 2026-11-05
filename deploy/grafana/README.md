# Grafana for Cache Me Outside (plan #131)

1. Run Prometheus with `--web.enable-otlp-receiver`, then point `tools/otlp` (#40) at `http://<prometheus>:9090/api/v1/otlp/v1/metrics`.
2. Mount `provisioning/` at `/etc/grafana/provisioning` and `dashboards/` at `/var/lib/grafana/dashboards/cmo`. Set `CMO_PROMETHEUS_URL`.
3. After changing panels, regenerate with `python3 tools/grafana/gen_dashboards.py`.

The two dashboards are an overview of all databases and a per-tenant view with a `$db` picker. They chart every metric the OTLP exporter sends.
