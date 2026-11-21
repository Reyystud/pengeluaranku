"""Writes ``monitoring/dashboards/*.json`` (PRD 18.6): ``python monitoring/build_dashboards.py``.

The JSON files are the artefact Grafana loads; this generator only keeps panel boilerplate in one
place. A test (``monitoring/tests``) checks that every query uses a metric the services register.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}


def panel(
    pid: int,
    title: str,
    exprs: list[tuple[str, str]],
    x: int,
    y: int,
    *,
    kind: str = "timeseries",
    unit: str = "short",
    w: int = 12,
    h: int = 8,
    description: str = "",
) -> dict[str, Any]:
    return {
        "id": pid,
        "type": kind,
        "title": title,
        "description": description,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "targets": [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": DS}
            for i, (expr, legend) in enumerate(exprs)
        ],
    }


def note(
    pid: int, title: str, text: str, x: int, y: int, w: int = 24, h: int = 4
) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "text",
        "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": text},
    }


def dashboard(uid: str, title: str, panels: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "uid": uid,
        "title": title,
        "tags": ["sei"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "panels": panels,
    }


def q(p: float, metric: str, by: str = "service, route") -> str:
    return f"histogram_quantile({p}, sum by (le, {by}) (rate({metric}_bucket[5m])))"


SERVICE_HEALTH = dashboard(
    "sei-service-health",
    "Service health",
    [
        panel(
            1,
            "Backend latency P50 / P95 / P99",
            [
                (q(0.5, "http_request_duration_seconds", "service"), "P50 {{service}}"),
                (q(0.95, "http_request_duration_seconds", "service"), "P95 {{service}}"),
                (q(0.99, "http_request_duration_seconds", "service"), "P99 {{service}}"),
            ],
            0,
            0,
            unit="s",
            description="SLO: backend CRUD P95 <= 300 ms, POST /transactions <= 500 ms (PRD 5.3).",
        ),
        panel(
            2,
            "P95 latency per route",
            [
                (q(0.95, "http_request_duration_seconds"), "{{service}} {{route}}"),
            ],
            12,
            0,
            unit="s",
        ),
        panel(
            3,
            "Throughput (req/s)",
            [
                ("sum by (service) (rate(http_requests_total[5m]))", "{{service}}"),
            ],
            0,
            8,
            unit="reqps",
        ),
        panel(
            4,
            "5xx error rate",
            [
                (
                    'sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))',
                    "5xx share",
                ),
            ],
            12,
            8,
            unit="percentunit",
            description="Alert: more than 2% for 5 minutes.",
        ),
        panel(
            5,
            "ML circuit state",
            [("max(ml_circuit_state)", "0 closed, 1 half-open, 2 open")],
            0,
            16,
            kind="stat",
        ),
        panel(
            6,
            "ML client calls by outcome",
            [
                ("sum by (outcome) (rate(ml_client_requests_total[5m]))", "{{outcome}}"),
            ],
            6,
            16,
            w=9,
        ),
        panel(
            7,
            "ML client latency P95",
            [
                (q(0.95, "ml_client_duration_seconds", "endpoint"), "{{endpoint}}"),
            ],
            15,
            16,
            w=9,
            unit="s",
        ),
        note(
            8,
            "Not shown locally",
            "CPU, memory, instance count, cold starts and the database pool come from Cloud Run "
            "and Cloud SQL metrics in Cloud Monitoring (PRD 18.1); they have no local equivalent.",
            0,
            24,
        ),
    ],
)

MODEL_HEALTH = dashboard(
    "sei-model-health",
    "Model health",
    [
        panel(
            1,
            "Confidence distribution (ML service)",
            [
                ("sum by (le) (increase(prediction_confidence_bucket[1h]))", "{{le}}"),
            ],
            0,
            0,
            kind="barchart",
            description="Cumulative buckets of top-1 calibrated confidence, last hour.",
        ),
        panel(
            2,
            "Decision mix (ML service)",
            [
                ("sum by (decision) (rate(predictions_total[15m]))", "{{decision}}"),
            ],
            12,
            0,
            description="auto_apply / suggest / needs_review.",
        ),
        panel(
            3,
            "Stored decisions by source (backend)",
            [
                (
                    "sum by (decision, source) (rate(categorization_decisions_total[1h]))",
                    "{{decision}} / {{source}}",
                ),
            ],
            0,
            8,
        ),
        panel(
            4,
            "Correction rate (proxy)",
            [
                (
                    'sum(rate(category_feedback_total{feedback_type="correction"}[1d])) / sum(rate(category_feedback_total[1d]))',
                    "corrections / feedback",
                ),
            ],
            12,
            8,
            unit="percentunit",
            description="Proxy: users do not correct every mistake (PRD 18.5).",
        ),
        panel(
            5,
            "Feedback by model version",
            [
                (
                    "sum by (model_version, feedback_type) (increase(category_feedback_total[7d]))",
                    "{{model_version}} {{feedback_type}}",
                ),
            ],
            0,
            16,
        ),
        panel(
            6,
            "Predicted category distribution",
            [
                ("sum by (category) (increase(predicted_category_total[1d]))", "{{category}}"),
            ],
            12,
            16,
            kind="barchart",
        ),
        panel(
            7,
            "Loaded model versions",
            [
                ("model_loaded_info", "{{model}} {{version}} ({{alias}})"),
            ],
            0,
            24,
            kind="table",
        ),
        panel(
            8,
            "Model load failures",
            [
                ("sum by (reason) (increase(model_load_failures_total[1d]))", "{{reason}}"),
            ],
            12,
            24,
        ),
        panel(
            9,
            "Anomalies by severity",
            [
                (
                    "sum by (type, severity, is_alert) (increase(anomalies_total[1d]))",
                    "{{type}} {{severity}} alert={{is_alert}}",
                ),
            ],
            0,
            32,
        ),
        note(
            10,
            "Shadow agreement",
            "Not available: the shadow evaluation job is built in a later task (PRD 16).",
            12,
            32,
            w=12,
        ),
    ],
)

DATA_HEALTH = dashboard(
    "sei-data-health",
    "Data health",
    [
        panel(
            1,
            "CSV imports by stage and outcome",
            [
                (
                    "sum by (stage, outcome) (increase(csv_imports_total[1d]))",
                    "{{stage}} {{outcome}}",
                ),
            ],
            0,
            0,
        ),
        panel(
            2,
            "Import rejection share",
            [
                (
                    'sum(increase(csv_imports_total{outcome="rejected"}[1d])) / sum(increase(csv_imports_total{stage="preview"}[1d]))',
                    "rejected / previews",
                ),
            ],
            12,
            0,
            unit="percentunit",
        ),
        panel(
            3,
            "Prediction inputs by decision (volume)",
            [
                ("sum(increase(predictions_total[1d]))", "predictions per day"),
            ],
            0,
            8,
        ),
        note(
            4,
            "Drift and quarantine",
            "Unseen-merchant share, feature PSI and quarantine counts come from the Evidently "
            "drift job (PRD 18.3, task T-35). Until it runs these panels do not exist; the HTML "
            "report goes to `gs://<project>-reports/drift/`.",
            12,
            8,
            w=12,
        ),
    ],
)

PIPELINES = dashboard(
    "sei-pipelines-jobs",
    "Pipelines and jobs",
    [
        panel(
            1,
            "Job runs by status",
            [
                ("sum by (job, status) (increase(jobs_runs_total[1d]))", "{{job}} {{status}}"),
            ],
            0,
            0,
            description="Filled by the batch jobs of task T-37.",
        ),
        panel(
            2,
            "Job duration P95",
            [
                (q(0.95, "job_duration_seconds", "job"), "{{job}}"),
            ],
            12,
            0,
            unit="s",
        ),
        panel(3, "Outbox pending events", [("max(outbox_pending)", "pending")], 0, 8, kind="stat"),
        panel(
            4,
            "Oldest unpublished outbox event",
            [("max(outbox_oldest_age_seconds)", "age")],
            6,
            8,
            kind="stat",
            unit="s",
            description="Alert above 5 minutes.",
        ),
        panel(
            5,
            "Events published",
            [
                (
                    "sum by (event_type, outcome) (rate(events_published_total[5m]))",
                    "{{event_type}} {{outcome}}",
                ),
            ],
            12,
            8,
        ),
        panel(
            6,
            "Events consumed",
            [
                (
                    "sum by (consumer, outcome) (rate(events_consumed_total[5m]))",
                    "{{consumer}} {{outcome}}",
                ),
            ],
            0,
            16,
        ),
        note(
            7,
            "DLQ and production model age",
            "The dead-letter backlog is a Pub/Sub metric (Cloud Monitoring alert "
            "`transaction-events-dlq`); model promotion history is in MLflow (PRD 16).",
            12,
            16,
            w=12,
        ),
    ],
)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, board in {
        "service-health": SERVICE_HEALTH,
        "model-health": MODEL_HEALTH,
        "data-health": DATA_HEALTH,
        "pipelines-jobs": PIPELINES,
    }.items():
        (OUT / f"{name}.json").write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
