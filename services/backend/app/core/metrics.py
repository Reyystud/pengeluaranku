"""Prometheus metrics for the backend (PRD 18.2). Route labels use templates, never raw paths."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["service", "route", "method", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["service", "route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ML_CLIENT_REQUESTS = Counter(
    "ml_client_requests_total", "Calls to the ML service", ["endpoint", "outcome"]
)
ML_CLIENT_DURATION = Histogram(
    "ml_client_duration_seconds",
    "ML service call duration",
    ["endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
ML_CIRCUIT_STATE = Gauge("ml_circuit_state", "ML circuit breaker: 0 closed, 1 half-open, 2 open")
CATEGORIZE_PREVIEW = Counter(
    "categorize_preview_total", "categorize-preview calls (no user data in labels)", ["decision"]
)

# -- PRD 18.2. Label values are enums or bounded names: never user ids, transaction ids, merchants.
CATEGORIZATION_DECISIONS = Counter(
    "categorization_decisions_total",
    "Stored categorization decisions",
    ["decision", "source"],
)
CATEGORY_FEEDBACK = Counter(
    "category_feedback_total",
    "Category feedback (confirmation, quick_pick, correction) by model version",
    ["feedback_type", "model_version"],
)
CSV_IMPORTS = Counter("csv_imports_total", "CSV import steps", ["stage", "outcome"])
EVENTS_PUBLISHED = Counter(
    "events_published_total", "Outbox events published or drained", ["event_type", "outcome"]
)
OUTBOX_PENDING = Gauge("outbox_pending", "Outbox events not yet published")
OUTBOX_OLDEST_AGE = Gauge(
    "outbox_oldest_age_seconds", "Age of the oldest unpublished outbox event (0 when empty)"
)
EVENTS_CONSUMED = Counter(
    "events_consumed_total",
    "Event deliveries per consumer (processed, duplicate, stale, error)",
    ["consumer", "outcome"],
)
ANOMALIES = Counter("anomalies_total", "Anomalies created", ["type", "severity", "is_alert"])
JOB_RUNS = Counter("jobs_runs_total", "Batch job runs", ["job", "status"])
JOB_DURATION = Histogram(
    "job_duration_seconds",
    "Batch job duration",
    ["job"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600),
)


@contextmanager
def observe_job(job: str) -> Iterator[None]:
    """Count a job run as ``ok`` or ``error`` and time it (PRD 15; used by the jobs of T-37)."""
    started = time.perf_counter()
    try:
        yield
    except BaseException:
        JOB_RUNS.labels(job, "error").inc()
        raise
    else:
        JOB_RUNS.labels(job, "ok").inc()
    finally:
        JOB_DURATION.labels(job).observe(time.perf_counter() - started)
