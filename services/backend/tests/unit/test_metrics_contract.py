"""PRD 18.2 names exist in the registries, and ``observe_job`` counts runs (jobs arrive in T-37)."""

from __future__ import annotations

import pytest
from app.core.metrics import observe_job
from prometheus_client import REGISTRY

BACKEND = [
    "http_requests_total",
    "http_request_duration_seconds",
    "ml_client_requests_total",
    "ml_client_duration_seconds",
    "ml_circuit_state",
    "categorization_decisions_total",
    "category_feedback_total",
    "csv_imports_total",
    "events_published_total",
    "outbox_pending",
    "outbox_oldest_age_seconds",
    "events_consumed_total",
    "anomalies_total",
    "jobs_runs_total",
    "job_duration_seconds",
]


def names() -> set[str]:
    return {m.name for m in REGISTRY.collect()}


@pytest.mark.parametrize("metric", BACKEND)
def test_18_2_backend_metric_is_registered(metric: str) -> None:
    import app.main  # noqa: F401  (imports every module that defines or uses a metric)

    # prometheus_client strips the `_total` suffix from counter family names.
    assert metric.removesuffix("_total") in names()


def test_18_2_observe_job_counts_ok_and_error_runs_and_times_them() -> None:
    ok = lambda s: REGISTRY.get_sample_value("jobs_runs_total", {"job": "t34", "status": s}) or 0.0  # noqa: E731
    before = (ok("ok"), ok("error"))
    with observe_job("t34"):
        pass
    with pytest.raises(RuntimeError), observe_job("t34"):
        raise RuntimeError("boom")
    assert (ok("ok"), ok("error")) == (before[0] + 1, before[1] + 1)
    assert REGISTRY.get_sample_value("job_duration_seconds_count", {"job": "t34"}) == 2
