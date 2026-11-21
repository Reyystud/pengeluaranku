"""PRD 18.2 application metrics are incremented by the real code paths, with bounded labels."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import Engine

from tests.integration.conftest import API, signup
from tests.integration.test_anomalies_api import seed_regular, spike, user_id_of
from tests.integration.test_imports_api import HEADER, YESTERDAY, commit, preview
from tests.integration.test_transactions_api import make

pytestmark = pytest.mark.integration


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


def test_18_2_saving_a_transaction_counts_its_decision_and_the_event_flow(
    client: TestClient, auth: dict[str, str]
) -> None:
    decision = {"decision": "needs_review", "source": "fallback"}
    published = {"event_type": "transaction.created", "outcome": "ok"}
    consumed = {"consumer": "anomaly-scorer", "outcome": "processed"}
    before = (
        sample("categorization_decisions_total", **decision),
        sample("events_published_total", **published),
        sample("events_consumed_total", **consumed),
    )
    make(client, auth, description="Warung metrik")
    after = (
        sample("categorization_decisions_total", **decision),
        sample("events_published_total", **published),
        sample("events_consumed_total", **consumed),
    )
    assert [a - b for a, b in zip(after, before, strict=True)] == [1, 1, 1]


def test_18_2_changing_a_category_counts_feedback_by_model_version(
    client: TestClient, auth: dict[str, str]
) -> None:
    tx = make(client, auth, description="Warung umpan balik")
    before = sample("category_feedback_total", feedback_type="correction", model_version="none")
    r = client.patch(f"{API}/transactions/{tx['id']}", json={"category": "shopping"}, headers=auth)
    assert r.status_code == 200
    after = sample("category_feedback_total", feedback_type="correction", model_version="none")
    assert after == before + 1


def test_18_2_csv_import_steps_are_counted(client: TestClient, auth: dict[str, str]) -> None:
    before = (
        sample("csv_imports_total", stage="preview", outcome="ok"),
        sample("csv_imports_total", stage="commit", outcome="ok"),
        sample("csv_imports_total", stage="preview", outcome="rejected"),
    )
    body = preview(client, auth, f"{YESTERDAY},Kopi,25000,expense,cash,,,")
    assert commit(client, auth, body["import_id"]).status_code == 200
    bad = client.post(
        f"{API}/transactions/imports",
        files={"file": ("a.csv", b"\xff\xfe nonsense", "text/csv")},
        headers=auth,
    )
    assert bad.status_code >= 400
    assert HEADER  # the helper header is the one the import accepts
    after = (
        sample("csv_imports_total", stage="preview", outcome="ok"),
        sample("csv_imports_total", stage="commit", outcome="ok"),
        sample("csv_imports_total", stage="preview", outcome="rejected"),
    )
    assert [a - b for a, b in zip(after, before, strict=True)] == [1, 1, 1]


def test_18_2_anomalies_are_counted_by_type_severity_and_alert(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    labels = {"type": "amount_spike", "severity": "high", "is_alert": "true"}
    before = sample("anomalies_total", **labels)
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth)
    assert sample("anomalies_total", **labels) == before + 1


def test_18_2_metrics_endpoint_exposes_outbox_gauges_and_no_user_data(
    client: TestClient, auth: dict[str, str]
) -> None:
    secret = "Warung-Rahasia-Metrik"
    make(client, auth, description=secret)
    text = client.get("/metrics").text
    assert "outbox_pending " in text and "outbox_oldest_age_seconds " in text
    assert secret not in text and secret.lower() not in text
    # No uuid anywhere in a label: ids are never labels (PRD 18.2).
    labels = re.findall(r"\{[^}]*\}", text)
    assert not any(re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}", label) for label in labels)
