"""ML client, circuit breaker and categorization rules (PRD 6.3, 6.4, 7.3.4, FR-03.10)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from app.clients.ml import (
    BATCH_LIMIT,
    CircuitBreaker,
    MlClient,
    MlResult,
)
from app.core.config import Settings
from app.models import Category
from app.services.categorization import CategorizeInput, MlCategorizer

from ml.taxonomy import CATEGORIES

URL = "http://ml.test"


def settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="ci", ml_service_url=URL, **over)  # type: ignore[call-arg]


def prediction(
    slug: str = "food_beverage", confidence: float = 0.95, **over: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "predicted_category": slug,
        "confidence": confidence,
        "decision": "auto_apply",
        "alternatives": [
            {"category": "groceries", "confidence": 0.03},
            {"category": "shopping", "confidence": 0.01},
        ],
        "model_version": "transaction-classifier@7",
        "feature_version": "features-1",
        "thresholds": {"t_high": 0.9, "t_low": 0.6},
        "latency_ms": 6.0,
        "shadow": None,
    }
    body.update(over)
    return body


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def client_with(handler: Any, **kw: Any) -> MlClient:
    return MlClient(settings(), transport=httpx.MockTransport(handler), **kw)


PAYLOAD = {"request_id": "r-0", "description": "x"}


def test_6_3_success_parses_the_documented_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=prediction())

    result = client_with(handler).classify(PAYLOAD, request_id="req-9")
    assert result.error is None and result.prediction is not None
    assert result.prediction.predicted_category == "food_beverage"
    assert result.prediction.thresholds.t_high == 0.9
    assert seen[0].url.path == "/v1/classify" and seen[0].headers["x-request-id"] == "req-9"
    assert json.loads(seen[0].content) == PAYLOAD


def test_6_3_a_timeout_is_not_retried_and_never_raises() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    result = client_with(handler).classify(PAYLOAD)
    assert result == MlResult(error="timeout") and len(calls) == 1


def test_6_3_connection_errors_are_retried_exactly_once() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("refused")

    assert client_with(handler).classify(PAYLOAD).error == "unavailable"
    assert len(calls) == 2

    flaky = []

    def recovers(request: httpx.Request) -> httpx.Response:
        flaky.append(1)
        if len(flaky) == 1:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json=prediction())

    assert client_with(recovers).classify(PAYLOAD).prediction is not None


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503, json={"code": "MODEL_NOT_AVAILABLE"}), "unavailable"),
        (httpx.Response(500, text="boom"), "unavailable"),
        (httpx.Response(200, text="not json"), "bad_response"),
        (httpx.Response(200, json={"predicted_category": "x"}), "bad_response"),
        (httpx.Response(200, json=prediction(decision="maybe")), "bad_response"),
        (httpx.Response(422, json={"code": "VALIDATION_ERROR"}), "rejected"),
    ],
)
def test_6_3_every_failure_mode_becomes_an_error_code(response: httpx.Response, error: str) -> None:
    assert client_with(lambda request: response).classify(PAYLOAD) == MlResult(error=error)


def test_6_3_an_empty_url_disables_the_client_without_network() -> None:
    client = MlClient(Settings(_env_file=None, app_env="ci"))  # type: ignore[call-arg]
    assert client.enabled is False
    assert client.classify(PAYLOAD).error == "disabled"
    assert [r.error for r in client.classify_batch([PAYLOAD] * 3)] == ["disabled"] * 3


def test_6_3_batches_are_chunked_and_keep_their_order() -> None:
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        items = json.loads(request.content)["items"]
        sizes.append(len(items))
        return httpx.Response(
            200, json={"items": [prediction(confidence=i["n"] / 2000) for i in items]}
        )

    payloads = [{"n": n} for n in range(1, 1202)]
    results = client_with(handler).classify_batch(payloads)
    assert sizes == [BATCH_LIMIT, BATCH_LIMIT, 201]
    assert [r.prediction.confidence for r in results if r.prediction] == [
        n / 2000 for n in range(1, 1202)
    ]


def test_6_3_a_batch_with_the_wrong_item_count_is_a_bad_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [prediction()]})

    assert [r.error for r in client_with(handler).classify_batch([PAYLOAD] * 3)] == [
        "bad_response"
    ] * 3


# --- circuit breaker (6.4) ---------------------------------------------------------------------
def test_6_4_opens_after_5_consecutive_failures_and_skips_calls() -> None:
    clock, calls = Clock(), []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500)

    client = client_with(handler, breaker=CircuitBreaker(5, 30.0, clock))
    for _ in range(5):
        assert client.classify(PAYLOAD).error == "unavailable"
    assert client.breaker.state == "open"
    before = len(calls)
    assert client.classify(PAYLOAD).error == "circuit_open"
    assert len(calls) == before  # skipped: no network call while open


def test_6_4_half_open_allows_one_trial_then_closes_or_reopens() -> None:
    clock, ok = Clock(), [False]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=prediction()) if ok[0] else httpx.Response(500)

    client = client_with(handler, breaker=CircuitBreaker(5, 30.0, clock))
    for _ in range(5):
        client.classify(PAYLOAD)
    clock.now += 29
    assert client.classify(PAYLOAD).error == "circuit_open"  # still open at 29 s
    clock.now += 2
    assert client.classify(PAYLOAD).error == "unavailable"  # the half-open trial fails
    assert client.breaker.state == "open"
    assert client.classify(PAYLOAD).error == "circuit_open"  # a fresh 30 s starts
    clock.now += 31
    ok[0] = True
    assert client.classify(PAYLOAD).prediction is not None  # trial succeeds
    assert client.breaker.state == "closed"
    assert client.classify(PAYLOAD).prediction is not None


def test_6_4_half_open_lets_only_one_request_through() -> None:
    clock = Clock()
    breaker = CircuitBreaker(2, 30.0, clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow()
    clock.now += 31
    assert breaker.allow() is True  # the trial
    assert breaker.state == "half_open" and breaker.allow() is False  # everyone else waits


def test_6_4_opens_on_a_failure_rate_above_half_in_the_last_20_calls() -> None:
    breaker = CircuitBreaker(consecutive=50, open_seconds=30.0, clock=Clock())
    for i in range(20):  # alternate so there are never 5 failures in a row
        breaker.allow()
        breaker.record_failure() if i % 3 else breaker.record_success()
    assert breaker.state == "open"  # 13 failures of 20

    healthy = CircuitBreaker(consecutive=50, open_seconds=30.0, clock=Clock())
    for i in range(40):
        healthy.allow()
        healthy.record_failure() if i % 3 == 0 else healthy.record_success()
    assert healthy.state == "closed"  # a third of the calls fail: below 50%


def test_6_4_a_rejected_request_does_not_trip_the_breaker() -> None:
    client = client_with(lambda request: httpx.Response(422, json={}), breaker=CircuitBreaker())
    for _ in range(10):
        assert client.classify(PAYLOAD).error == "rejected"
    assert client.breaker.state == "closed"


# --- contract with the real ML service schemas ---------------------------------------------------
def test_14_2_requests_and_responses_match_the_ml_service_contract() -> None:
    schemas = pytest.importorskip("ml_service.schemas")
    from datetime import UTC, datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo

    user = type("U", (), {"timezone": "Asia/Jakarta"})()
    item = CategorizeInput(
        "expense", "STARBUCKS GRAND INDONESIA", "Starbucks", "starbucks", Decimal("45000"),
        "e_wallet", datetime(2026, 11, 18, 5, 30, tzinfo=UTC), True,
    )  # fmt: skip
    payload = MlCategorizer._payload(user, item, "req-1", 0)  # type: ignore[arg-type]
    parsed = schemas.ClassifyRequest.model_validate(payload)  # extra="forbid": no stray fields
    assert parsed.local_hour == 12 and parsed.weekday == 2  # Jakarta is UTC+7, Wednesday
    assert set(payload) == set(schemas.ClassifyRequest.model_fields)
    untimed = MlCategorizer._payload(user, CategorizeInput(*item.__dict__.values()), "r", 1)  # type: ignore[arg-type]
    assert untimed["request_id"] == "r-1"
    assert datetime.now(ZoneInfo("Asia/Jakarta"))  # zoneinfo data is present

    response = schemas.ClassifyResponse(
        predicted_category="food_beverage", confidence=0.97, decision="auto_apply",
        alternatives=[schemas.Alternative(category="groceries", confidence=0.02)],
        model_version="transaction-classifier@7", feature_version="features-1",
        thresholds=schemas.Thresholds(t_high=0.9, t_low=0.6), latency_ms=6.0,
    )  # fmt: skip
    result = client_with(
        lambda request: httpx.Response(200, json=json.loads(response.model_dump_json()))
    ).classify(payload)
    assert result.prediction is not None and result.prediction.confidence == 0.97


# --- interpretation of a prediction (7.3.4, FR-03.10) -----------------------------------------
BY_SLUG = {
    c.slug: Category(
        id=uuid.uuid4(),
        slug=c.slug,
        name=c.display_name,
        transaction_type=c.transaction_type,
        is_model_label=c.slug != "uncategorized",
        sort_order=i,
    )  # fmt: skip
    for i, c in enumerate(CATEGORIES)
}


def categorizer() -> MlCategorizer:
    by_id = {c.id: c for c in BY_SLUG.values()}
    return MlCategorizer(None, MlClient(Settings(_env_file=None, app_env="ci")), BY_SLUG, by_id)  # type: ignore[arg-type,call-arg]


def interpret(slug: str, confidence: float, tx_type: str = "expense", **over: Any) -> Any:
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.clients.ml import MlPrediction

    pred = MlPrediction.model_validate(
        prediction(slug, confidence, decision=over.pop("decision", "auto_apply"), **over)
    )
    item = CategorizeInput(tx_type, "d", "m", "k", Decimal(1), "cash", datetime.now(UTC), False)
    return categorizer()._interpret(item, MlResult(prediction=pred))


def test_7_3_4_decisions_map_to_status_and_stored_category() -> None:
    auto = interpret("food_beverage", 0.95)
    assert (auto.category.slug, auto.status, auto.decision, auto.source) == (
        "food_beverage", "auto", "auto_apply", "model",
    )  # fmt: skip
    suggest = interpret("food_beverage", 0.7, decision="suggest")
    assert (suggest.category.slug, suggest.status) == ("food_beverage", "suggested")
    review = interpret("food_beverage", 0.3, decision="needs_review")
    assert (review.category.slug, review.status, review.decision) == (
        "uncategorized", "needs_review", "needs_review",
    )  # fmt: skip
    assert review.predicted.slug == "food_beverage"  # kept for quick picks
    assert [a["category"] for a in review.alternatives] == ["groceries", "shopping"]
    assert review.model_version == "transaction-classifier@7" and review.latency_ms == 6.0


def test_fr_03_10_type_consistency_uses_the_best_compatible_alternative() -> None:
    alts = [
        {"category": "groceries", "confidence": 0.03},
        {"category": "salary", "confidence": 0.02},
    ]
    # An income transaction predicted as an expense category: groceries is also an expense,
    # so salary (rank 3) is the first compatible one; its low confidence means review.
    result = interpret("food_beverage", 0.95, tx_type="income", alternatives=alts)
    assert result.predicted.slug == "food_beverage"
    assert result.status == "needs_review" and result.category.slug == "uncategorized"
    assert result.confidence == 0.02

    confident = interpret(
        "food_beverage",
        0.5,
        tx_type="income",
        alternatives=[
            {"category": "salary", "confidence": 0.92},
            {"category": "groceries", "confidence": 0.01},
        ],
    )
    assert (confident.category.slug, confident.status, confident.decision) == (
        "salary",
        "auto",
        "auto_apply",
    )  # decided with the model's own thresholds

    none_fit = interpret("food_beverage", 0.95, tx_type="income")
    assert none_fit.status == "needs_review" and none_fit.decision == "needs_review"


def test_6_3_a_label_outside_the_taxonomy_is_treated_as_a_bad_response() -> None:
    result = interpret("crypto_gains", 0.99)
    assert result.source == "fallback" and result.ml_error == "bad_response"
    assert result.category.slug == "uncategorized"


def test_6_3_ml_failures_become_fallback_with_the_error_code() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    item = CategorizeInput("expense", "d", "m", "k", Decimal(1), "cash", datetime.now(UTC), False)
    for error in ("timeout", "unavailable", "circuit_open", "disabled"):
        out = categorizer()._interpret(item, MlResult(error=error))
        assert (out.status, out.source, out.ml_error) == ("needs_review", "fallback", error)
        assert out.category.slug == "uncategorized" and out.confidence is None
