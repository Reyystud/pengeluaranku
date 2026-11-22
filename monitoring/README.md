# Monitoring (PRD 18)

| Path | What |
|---|---|
| `prometheus/prometheus.yml`, `prometheus/alerts.yml` | Local scrape config (backend, worker, ml-service) and alert rules |
| `dashboards/*.json` | Grafana dashboards: service health, model health, data health, pipelines and jobs |
| `build_dashboards.py` | Generates the dashboard JSON (`make dashboards`); edit it, not the JSON |
| `grafana/provisioning/` | Data source and dashboard provider, mounted by compose |
| `tests/` | Every dashboard query and alert expression uses a metric the services register |

Local: `make up-observability` starts Prometheus on <http://127.0.0.1:9090> and Grafana on
<http://127.0.0.1:3001> (anonymous viewer; admin password `GRAFANA_ADMIN_PASSWORD`, default `admin`,
local only).

GCP: the system layer is alerted by Cloud Monitoring (`infrastructure/terraform/monitoring.tf`);
application metrics are not scraped there (Managed Service for Prometheus needs a collector
sidecar). Prediction logs reach BigQuery through a Log Router sink.

Panels backed by later tasks (drift summary T-35, job runs T-37, shadow agreement) are marked in
the dashboards and show no data until those exist. Alert runbook links point to `docs/RUNBOOK.md`
(task T-36), which does not exist yet.

## Drift reports (T-35)

```bash
docker compose logs --no-log-prefix ml-service > ml-service.log
make drift-report LOGS=ml-service.log          # production model's reference, via MLflow
make drift-report LOGS=ml-service.log REFERENCE=models/transaction-classifier/<run>/reference
```

The report lands in `data/reports/drift/<date>/` (`report.html`, `summary.json`). Settings:
`config/drift.yaml`. The run needs at least 100 prediction lines in the 7-day window, otherwise it is
`skipped`. Models trained before T-35 have no `reference/` folder: retrain first.
