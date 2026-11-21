"""Emulator bootstrap for local EVENT_BUS=pubsub (PRD 7.11 FR-11.06)."""

from __future__ import annotations

import json

import httpx
import pytest
from app.events import bootstrap


def test_fr_11_06_bootstrap_creates_topics_dlq_and_a_push_subscription_per_prd_14_3() -> None:
    seen: list[tuple[str, dict[str, object]]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={})

    with httpx.Client(base_url="http://emu", transport=httpx.MockTransport(respond)) as client:
        bootstrap.bootstrap(client, "p", "http://worker:8000/internal/events/transaction")
    paths = [p for p, _ in seen]
    assert paths == [
        "/v1/projects/p/topics/transaction-events",
        "/v1/projects/p/topics/transaction-events-dlq",
        "/v1/projects/p/subscriptions/transaction-events-dlq-inspect",
        "/v1/projects/p/subscriptions/transaction-events-worker",
    ]
    sub = seen[-1][1]
    assert sub["pushConfig"] == {"pushEndpoint": "http://worker:8000/internal/events/transaction"}
    assert sub["ackDeadlineSeconds"] == 60
    assert sub["retryPolicy"] == {"minimumBackoff": "10s", "maximumBackoff": "600s"}
    assert sub["deadLetterPolicy"] == {
        "deadLetterTopic": "projects/p/topics/transaction-events-dlq",
        "maxDeliveryAttempts": 5,
    }


def test_fr_11_06_bootstrap_is_idempotent_and_surfaces_real_errors() -> None:
    exists = httpx.MockTransport(lambda r: httpx.Response(409, json={}))
    with httpx.Client(base_url="http://emu", transport=exists) as client:
        bootstrap.bootstrap(client, "p", "http://w")  # already there: fine
    broken = httpx.MockTransport(lambda r: httpx.Response(500))
    with httpx.Client(base_url="http://emu", transport=broken) as client:
        with pytest.raises(httpx.HTTPStatusError):
            bootstrap.bootstrap(client, "p", "http://w")


def test_fr_11_06_main_requires_its_settings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("PUBSUB_EMULATOR_HOST", "PUBSUB_PROJECT_ID", "PUSH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    assert bootstrap.main([]) == 2
    assert "required" in capsys.readouterr().err
