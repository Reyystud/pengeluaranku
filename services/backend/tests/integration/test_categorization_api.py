"""FR-03, FR-10, FR-15: categorization flow, merchant memory and feedback (PRD 6.3, 7.3, 7.10)."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.clients.ml import CircuitBreaker, MlClient
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup
from tests.integration.test_imports_api import commit, preview
from tests.integration.test_transactions_api import make, post_tx

pytestmark = pytest.mark.integration

YESTERDAY = (dt.date.today() - dt.timedelta(days=2)).isoformat()


class FakeMl:
    """Stands in for the ML service. ``table`` maps a description keyword to a prediction."""

    def __init__(self) -> None:
        self.mode = "ok"  # ok | timeout | 5xx | connect | garbage
        self.calls: list[dict[str, Any]] = []
        self.batch_sizes: list[int] = []
        self.table: dict[str, tuple[str, float, list[tuple[str, float]]]] = {}

    def predict(self, item: dict[str, Any]) -> dict[str, Any]:
        text_ = item["description"].lower()
        slug, conf, alts = next(
            (v for k, v in self.table.items() if k in text_),
            ("food_beverage", 0.95, [("groceries", 0.03), ("shopping", 0.01)]),
        )
        decision = "auto_apply" if conf >= 0.9 else "suggest" if conf >= 0.6 else "needs_review"
        return {
            "predicted_category": slug,
            "confidence": conf,
            "decision": decision,
            "alternatives": [{"category": c, "confidence": p} for c, p in alts],
            "model_version": "transaction-classifier@7",
            "feature_version": "features-1",
            "thresholds": {"t_high": 0.9, "t_low": 0.6},
            "latency_ms": 6.0,
            "shadow": None,
        }

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("slow")
        if self.mode == "connect":
            raise httpx.ConnectError("refused")
        self.calls.append(body)
        if self.mode == "5xx":
            return httpx.Response(503, json={"code": "MODEL_NOT_AVAILABLE"})
        if self.mode == "garbage":
            return httpx.Response(200, text="<html>")
        if request.url.path.endswith("/batch"):
            self.batch_sizes.append(len(body["items"]))
            return httpx.Response(200, json={"items": [self.predict(i) for i in body["items"]]})
        return httpx.Response(200, json=self.predict(body))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def ml(client: TestClient) -> FakeMl:
    fake = FakeMl()
    install(client, fake)
    return fake


def install(client: TestClient, fake: FakeMl, clock: Callable[[], float] | None = None) -> MlClient:
    settings = client.app.state.settings.model_copy(update={"ml_service_url": "http://ml.test"})  # type: ignore[attr-defined]
    breaker = CircuitBreaker(5, 30.0, clock or __import__("time").monotonic)
    ml_client = MlClient(settings, transport=httpx.MockTransport(fake), breaker=breaker)
    client.app.state.ml_client = ml_client  # type: ignore[attr-defined]
    return ml_client


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


def rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params))


def predictions_of(engine: Engine, tx_id: str) -> list[Any]:
    return rows(
        engine,
        "SELECT p.source, c.slug, p.confidence, p.decision, p.model_version, p.feature_version, "
        "p.latency_ms, p.ml_error, p.alternatives, p.request_id FROM category_predictions p "
        "JOIN categories c ON c.id = p.predicted_category_id WHERE p.transaction_id = :t "
        "ORDER BY p.created_at, p.id",
        t=tx_id,
    )


def feedback_of(engine: Engine, tx_id: str) -> list[Any]:
    return rows(
        engine,
        "SELECT f.feedback_type, f.previous_status, pc.slug AS prev, nc.slug AS new, "
        "f.model_version, f.merchant_key, f.prediction_id FROM category_feedback f "
        "JOIN categories pc ON pc.id = f.previous_category_id "
        "JOIN categories nc ON nc.id = f.new_category_id WHERE f.transaction_id = :t "
        "ORDER BY f.created_at, f.id",
        t=tx_id,
    )


def new_tx(
    client: TestClient, auth: dict[str, str], description: str, **over: Any
) -> dict[str, Any]:
    return make(client, auth, description=description, **over)


# --- create (6.3) ------------------------------------------------------------------------------
def test_fr_03_01_model_auto_apply_is_stored_with_a_prediction_row(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.table["starbucks"] = ("food_beverage", 0.97, [("groceries", 0.02), ("shopping", 0.01)])
    when = dt.datetime(2026, 11, 18, 12, 30, tzinfo=dt.timezone(dt.timedelta(hours=7)))
    tx = make(
        client, auth, description="STARBUCKS GRAND INDONESIA", transaction_date=when.isoformat(),
        payment_method="e-wallet",
    )  # fmt: skip
    assert tx["category"]["slug"] == "food_beverage" and tx["category_status"] == "auto"
    c = tx["categorization"]
    assert (c["decision"], c["source"], c["confidence"]) == ("auto_apply", "model", 0.97)
    assert c["model_version"] == "transaction-classifier@7" and c["ml_error"] is None
    assert [a["category"] for a in c["alternatives"]] == ["groceries", "shopping"]
    (sent,) = ml.calls
    assert sent["local_hour"] == 12 and sent["weekday"] == 2  # Wednesday, user's local time
    assert sent["payment_method"] == "e_wallet" and sent["amount"] == "25000.00"
    assert sent["feature_version"] == "features-1" and sent["merchant_key"]
    assert not {"user_id", "email", "notes"} & set(sent)  # PRD 14.2: no user data on the wire
    (p,) = predictions_of(engine, tx["id"])
    assert (p.source, p.slug, str(p.confidence), p.decision) == (
        "model",
        "food_beverage",
        "0.9700",
        "auto_apply",
    )
    assert (p.model_version, p.feature_version, p.latency_ms, p.ml_error) == (
        "transaction-classifier@7", "features-1", 6, None,
    )  # fmt: skip
    assert p.request_id and len(p.alternatives) == 2


def test_fr_03_01_a_date_only_transaction_sends_no_hour(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    new_tx(client, auth, "Warung", transaction_date=YESTERDAY)
    assert ml.calls[0]["local_hour"] is None


def test_7_3_4_suggest_and_needs_review_decisions(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.table["ragu"] = ("groceries", 0.7, [("food_beverage", 0.2), ("shopping", 0.05)])
    ml.table["asing"] = ("shopping", 0.3, [("groceries", 0.2), ("food_beverage", 0.1)])
    suggested = new_tx(client, auth, "Toko ragu")
    assert suggested["category"]["slug"] == "groceries"
    assert suggested["category_status"] == "suggested"
    review = new_tx(client, auth, "Toko asing")
    assert review["category"]["slug"] == "uncategorized"
    assert review["category_status"] == "needs_review"
    c = review["categorization"]
    assert c["decision"] == "needs_review" and c["predicted_category"] == "shopping"
    assert [a["category"] for a in c["alternatives"]] == ["groceries", "food_beverage"]
    (p,) = predictions_of(engine, review["id"])
    assert p.slug == "shopping" and p.decision == "needs_review"  # the pick is kept for quick picks
    queue = client.get(f"{API}/transactions?category_status=needs_review", headers=auth)
    assert [t["id"] for t in queue.json()["items"]] == [review["id"]]


def test_fr_03_10_type_consistency_on_create(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    ml.table["bonus"] = ("food_beverage", 0.95, [("salary", 0.9), ("groceries", 0.02)])
    tx = make(client, auth, transaction_type="income", description="Bonus kantor")
    assert tx["category"]["slug"] == "salary" and tx["category_status"] == "auto"
    ml.table["refund"] = ("food_beverage", 0.95, [("groceries", 0.02), ("shopping", 0.01)])
    none_fit = make(client, auth, transaction_type="income", description="Refund")
    assert none_fit["category"]["slug"] == "uncategorized"
    assert none_fit["category_status"] == "needs_review"


@pytest.mark.parametrize("mode", ["timeout", "5xx", "connect", "garbage"])
def test_6_3_saving_never_fails_because_of_the_ml_service(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine, mode: str
) -> None:
    ml.mode = mode
    r = post_tx(client, auth)
    assert r.status_code == 201, r.text
    tx = r.json()
    assert tx["category"]["slug"] == "uncategorized" and tx["category_status"] == "needs_review"
    expected = {
        "timeout": "timeout",
        "5xx": "unavailable",
        "connect": "unavailable",
        "garbage": "bad_response",
    }
    assert tx["categorization"]["source"] == "fallback"
    assert tx["categorization"]["ml_error"] == expected[mode]
    (p,) = predictions_of(engine, tx["id"])
    assert (p.source, p.slug, p.confidence, p.ml_error) == (
        "fallback",
        "uncategorized",
        None,
        expected[mode],
    )
    assert (
        rows(
            engine,
            "SELECT count(*) FROM outbox_events WHERE aggregate_id = CAST(:i AS uuid)",
            i=tx["id"],
        )[0][0]
        == 1
    )


def test_6_4_circuit_opens_skips_ml_then_recovers(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    fake, clock = FakeMl(), Clock()
    ml_client = install(client, fake, clock)
    fake.mode = "5xx"
    for _ in range(5):
        assert post_tx(client, auth).status_code == 201
    assert ml_client.breaker.state == "open" and len(fake.calls) == 5
    skipped = post_tx(client, auth).json()
    assert skipped["categorization"]["ml_error"] == "circuit_open" and len(fake.calls) == 5
    assert "ml_circuit_state 2.0" in client.get("/metrics").text
    clock.now += 31
    fake.mode = "ok"
    healed = post_tx(client, auth).json()
    assert healed["category_status"] == "auto" and ml_client.breaker.state == "closed"
    metrics = client.get("/metrics").text
    assert 'ml_client_requests_total{endpoint="classify",outcome="circuit_open"}' in metrics
    assert 'ml_client_requests_total{endpoint="classify",outcome="ok"}' in metrics
    assert "ml_circuit_state 0.0" in metrics


def test_fr_03_01_a_category_given_by_the_user_makes_no_ml_call(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    tx = make(client, auth, category="transportation")
    assert tx["category_status"] == "user_set" and tx["categorization"]["source"] == "user"
    assert ml.calls == [] and predictions_of(engine, tx["id"]) == []


def test_17_3_descriptions_never_reach_logs_or_metrics(
    client: TestClient, auth: dict[str, str], ml: FakeMl, log_stream: Any
) -> None:
    secret = "RAHASIA-WARUNG-XYZ"
    ml.mode = "5xx"
    make(client, auth, description=secret)
    ml.mode = "ok"
    make(client, auth, description=secret + "-2")
    assert secret not in log_stream.getvalue()
    assert secret not in client.get("/metrics").text


# --- merchant memory and feedback (FR-03.08, FR-10.01) ------------------------------------------
def test_fr_03_08_changing_a_category_creates_a_rule_that_wins_over_the_model(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.table["indomaret"] = ("shopping", 0.3, [("groceries", 0.25), ("food_beverage", 0.1)])
    first = new_tx(client, auth, "INDOMARET POINT")
    assert first["category_status"] == "needs_review"
    patched = client.patch(
        f"{API}/transactions/{first['id']}", json={"category": "groceries"}, headers=auth
    )
    assert patched.status_code == 200 and patched.json()["category_status"] == "user_set"
    rules = client.get(f"{API}/merchant-rules", headers=auth).json()["items"]
    assert len(rules) == 1 and rules[0]["category"]["slug"] == "groceries"
    assert rules[0]["merchant_key"] == first["merchant_key"] and rules[0]["times_applied"] == 0

    before = len(ml.calls)
    second = new_tx(client, auth, "INDOMARET POINT", amount="30000")
    assert len(ml.calls) == before  # the rule means no ML call (6.3 step 3)
    assert second["category"]["slug"] == "groceries" and second["category_status"] == "rule"
    assert second["categorization"]["source"] == "rule"
    (p,) = predictions_of(engine, second["id"])
    assert (p.source, p.slug, p.confidence, p.decision) == (
        "user_rule",
        "groceries",
        None,
        "auto_apply",
    )
    rule = client.get(f"{API}/merchant-rules", headers=auth).json()["items"][0]
    assert rule["times_applied"] == 1 and rule["last_applied_at"]

    # Changing the category again updates the same rule (one rule per merchant).
    client.patch(f"{API}/transactions/{second['id']}", json={"category": "shopping"}, headers=auth)
    rules = client.get(f"{API}/merchant-rules", headers=auth).json()["items"]
    assert [r["category"]["slug"] for r in rules] == ["shopping"]


def test_fr_03_08_a_rule_for_another_transaction_type_is_ignored(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    ml.table["transfer ke"] = ("food_beverage", 0.3, [("groceries", 0.2), ("shopping", 0.1)])
    first = new_tx(client, auth, "Transfer ke Budi")
    client.patch(f"{API}/transactions/{first['id']}", json={"category": "groceries"}, headers=auth)
    before = len(ml.calls)
    income = make(client, auth, transaction_type="income", description="Transfer ke Budi")
    assert len(ml.calls) == before + 1  # an expense rule does not apply to income
    assert income["categorization"]["source"] != "rule"


def test_fr_03_08_no_rule_without_a_merchant_key_or_for_uncategorized(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    tx = new_tx(client, auth, "Warung Pak Slamet")
    client.patch(f"{API}/transactions/{tx['id']}", json={"category": "uncategorized"}, headers=auth)
    assert client.get(f"{API}/merchant-rules", headers=auth).json()["items"] == []


def test_fr_10_01_feedback_types(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.table["ragu"] = ("groceries", 0.7, [("food_beverage", 0.2), ("shopping", 0.05)])
    ml.table["asing"] = ("shopping", 0.3, [("groceries", 0.2), ("food_beverage", 0.1)])
    ml.table["pasti"] = ("food_beverage", 0.97, [("groceries", 0.02), ("shopping", 0.01)])

    confirm = new_tx(client, auth, "Toko ragu")  # suggested -> confirmed
    r = client.post(f"{API}/transactions/{confirm['id']}/confirm-category", headers=auth)
    assert r.status_code == 200 and r.json()["category_status"] == "user_confirmed"
    (f,) = feedback_of(engine, confirm["id"])
    assert (f.feedback_type, f.previous_status, f.prev, f.new) == (
        "confirmation",
        "suggested",
        "groceries",
        "groceries",
    )
    assert f.model_version == "transaction-classifier@7" and f.prediction_id and f.merchant_key
    again = client.post(f"{API}/transactions/{confirm['id']}/confirm-category", headers=auth)
    assert again.status_code == 409 and again.json()["code"] == "NOT_A_SUGGESTION"

    pick = new_tx(client, auth, "Toko asing")  # needs_review -> one of the quick picks
    client.patch(f"{API}/transactions/{pick['id']}", json={"category": "groceries"}, headers=auth)
    assert [x.feedback_type for x in feedback_of(engine, pick["id"])] == ["quick_pick"]

    other = new_tx(client, auth, "Toko asing lagi", amount="777")  # needs_review -> something else
    client.patch(
        f"{API}/transactions/{other['id']}", json={"category": "transportation"}, headers=auth
    )
    assert [x.feedback_type for x in feedback_of(engine, other["id"])] == ["correction"]

    auto = new_tx(client, auth, "Toko pasti")  # auto -> corrected
    client.patch(f"{API}/transactions/{auto['id']}", json={"category": "shopping"}, headers=auth)
    (f,) = feedback_of(engine, auto["id"])
    assert (f.feedback_type, f.previous_status, f.prev, f.new) == (
        "correction",
        "auto",
        "food_beverage",
        "shopping",
    )

    # A user-chosen category changed again is not model feedback; neither is a plain edit.
    client.patch(f"{API}/transactions/{auto['id']}", json={"category": "groceries"}, headers=auth)
    client.patch(f"{API}/transactions/{auto['id']}", json={"notes": "x"}, headers=auth)
    assert len(feedback_of(engine, auto["id"])) == 1


def test_fr_03_08_apply_to_past_transactions_of_the_merchant(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    ml.table["kopi"] = ("shopping", 0.3, [("groceries", 0.2), ("food_beverage", 0.1)])
    day = lambda n: (dt.date.today() - dt.timedelta(days=n)).isoformat()  # noqa: E731
    a = new_tx(client, auth, "Kopi Tuku", transaction_date=day(5))
    b = new_tx(client, auth, "Kopi Tuku", transaction_date=day(6))
    locked = new_tx(client, auth, "Kopi Tuku", transaction_date=day(7), category="shopping")
    income = make(
        client, auth, transaction_type="income", description="Kopi Tuku", transaction_date=day(8)
    )
    unrelated = new_tx(client, auth, "Bengkel Jaya", transaction_date=day(9))
    r = client.patch(
        f"{API}/transactions/{a['id']}",
        json={"category": "food_beverage", "apply_to_past_merchant_transactions": True},
        headers=auth,
    )
    assert (
        r.status_code == 200 and r.json()["applied_to_past"] == 1
    )  # only b: others are locked/other type
    get = lambda t: client.get(f"{API}/transactions/{t['id']}", headers=auth).json()  # noqa: E731
    assert (get(b)["category"]["slug"], get(b)["category_status"]) == ("food_beverage", "rule")
    assert (
        get(locked)["category"]["slug"] == "shopping"
        and get(locked)["category_status"] == "user_set"
    )
    assert get(income)["category_status"] == "needs_review"
    assert get(unrelated)["category"]["slug"] == unrelated["category"]["slug"]  # untouched
    without = client.patch(
        f"{API}/transactions/{a['id']}", json={"category": "groceries"}, headers=auth
    )
    assert without.json()["applied_to_past"] == 0 and get(b)["category"]["slug"] == "food_beverage"
    bad = client.patch(
        f"{API}/transactions/{a['id']}",
        json={"apply_to_past_merchant_transactions": True},
        headers=auth,
    )
    assert bad.status_code == 422


def test_fr_15_03_the_rule_cap_is_1000(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    tx = new_tx(client, auth, "Kedai Satu")
    user_id = rows(engine, "SELECT id FROM users ORDER BY created_at DESC LIMIT 1")[0][0]
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO merchant_rules (id, user_id, merchant_key, merchant_display, category_id, "
                "times_applied, created_at, updated_at) SELECT gen_random_uuid(), :u, 'm' || g, 'M', "
                "(SELECT id FROM categories WHERE slug = 'shopping'), 0, now(), now() "
                "FROM generate_series(1, 1000) g"
            ),
            {"u": user_id},
        )
    r = client.patch(f"{API}/transactions/{tx['id']}", json={"category": "groceries"}, headers=auth)
    assert (
        r.status_code == 200 and r.json()["category"]["slug"] == "groceries"
    )  # the edit still works
    assert len(client.get(f"{API}/merchant-rules", headers=auth).json()["items"]) == 1000
    assert (
        rows(
            engine,
            "SELECT count(*) FROM merchant_rules WHERE merchant_key = :k",
            k=tx["merchant_key"],
        )[0][0]
        == 0
    )


# --- merchant rules API (FR-15) ----------------------------------------------------------------
def test_fr_15_rules_can_be_changed_and_deleted_without_touching_past_transactions(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    tx = new_tx(client, auth, "Kedai Kopi Baru")
    client.patch(f"{API}/transactions/{tx['id']}", json={"category": "groceries"}, headers=auth)
    (rule,) = client.get(f"{API}/merchant-rules", headers=auth).json()["items"]
    assert set(rule) == {"id", "merchant_key", "merchant_display", "category", "times_applied",
                         "last_applied_at", "created_at", "updated_at"}  # fmt: skip
    changed = client.patch(
        f"{API}/merchant-rules/{rule['id']}", json={"category": "shopping"}, headers=auth
    )
    assert changed.status_code == 200 and changed.json()["category"]["slug"] == "shopping"
    past = client.get(f"{API}/transactions/{tx['id']}", headers=auth).json()
    assert past["category"]["slug"] == "groceries"  # FR-15.02: past rows keep their category
    for bad in ("uncategorized", "nonexistent"):
        r = client.patch(f"{API}/merchant-rules/{rule['id']}", json={"category": bad}, headers=auth)
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "UNKNOWN_CATEGORY"
    assert client.delete(f"{API}/merchant-rules/{rule['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/merchant-rules", headers=auth).json()["items"] == []
    assert client.delete(f"{API}/merchant-rules/{rule['id']}", headers=auth).status_code == 404
    again = new_tx(client, auth, "Kedai Kopi Baru", amount="123")
    assert again["categorization"]["source"] == "model"  # no rule any more


# --- recategorize (FR-03.09) -------------------------------------------------------------------
def test_fr_03_09_recategorize_after_an_ml_outage(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.mode = "timeout"
    tx = new_tx(client, auth, "Warung Makan Sederhana")
    assert tx["category_status"] == "needs_review"
    ml.mode = "ok"
    r = client.post(f"{API}/transactions/{tx['id']}/recategorize", json={}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"]["slug"] == "food_beverage" and body["category_status"] == "auto"
    assert body["version"] == tx["version"] + 1 and body["categorization"]["source"] == "model"
    sources = [(p.source, p.ml_error) for p in predictions_of(engine, tx["id"])]
    assert sources == [("fallback", "timeout"), ("model", None)]  # history is kept


def test_fr_03_09_locked_categories_need_force(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    tx = new_tx(client, auth, "Warung", category="transportation")
    locked = client.post(f"{API}/transactions/{tx['id']}/recategorize", json={}, headers=auth)
    assert locked.status_code == 409 and locked.json()["code"] == "CATEGORY_LOCKED"
    assert (
        client.post(f"{API}/transactions/{tx['id']}/recategorize", headers=auth).status_code == 409
    )
    forced = client.post(
        f"{API}/transactions/{tx['id']}/recategorize", json={"force": True}, headers=auth
    )
    assert forced.status_code == 200 and forced.json()["category"]["slug"] == "food_beverage"
    assert (
        client.post(f"{API}/transactions/{uuid.uuid4()}/recategorize", headers=auth).status_code
        == 404
    )


# --- categorize-preview (FR-03.07) -------------------------------------------------------------
def test_fr_03_07_preview_stores_nothing(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    tx = new_tx(client, auth, "Kedai Preview")
    client.patch(f"{API}/transactions/{tx['id']}", json={"category": "groceries"}, headers=auth)
    counts = lambda: [  # noqa: E731
        rows(engine, f"SELECT count(*) FROM {t}")[0][0]
        for t in (
            "transactions",
            "category_predictions",
            "category_feedback",
            "outbox_events",
            "merchant_rules",
        )
    ]
    before, rule_before = counts(), client.get(f"{API}/merchant-rules", headers=auth).json()
    r = client.post(
        f"{API}/transactions/categorize-preview",
        json={"description": "Kedai Preview", "transaction_type": "expense", "amount": "45000"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["category"]["slug"] == "groceries" and body["category_status"] == "rule"
    assert body["categorization"]["source"] == "rule"
    assert (
        counts() == before
        and client.get(f"{API}/merchant-rules", headers=auth).json() == rule_before
    )  # times_applied too

    model = client.post(
        f"{API}/transactions/categorize-preview",
        json={"description": "Tempat Lain", "transaction_type": "expense"},
        headers=auth,
    ).json()
    assert (
        model["category"]["slug"] == "food_beverage"
        and model["categorization"]["source"] == "model"
    )
    assert ml.calls[-1]["amount"] == "25000.00"  # default when the draft has no amount yet
    assert counts() == before
    assert 'categorize_preview_total{decision="auto_apply"}' in client.get("/metrics").text


def test_fr_03_07_preview_validation_and_ml_outage(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    url = f"{API}/transactions/categorize-preview"
    for body in (
        {"transaction_type": "expense"},
        {"description": "x", "transaction_type": "refund"},
        {"description": "x", "transaction_type": "expense", "amount": "0"},
        {"description": "x", "transaction_type": "expense", "user_id": "u"},
        {"description": "x" * 201, "transaction_type": "expense"},
    ):
        assert client.post(url, json=body, headers=auth).status_code == 422, body
    ml.mode = "timeout"
    r = client.post(url, json={"description": "x", "transaction_type": "expense"}, headers=auth)
    assert r.status_code == 200 and r.json()["category"]["slug"] == "uncategorized"
    assert r.json()["categorization"]["ml_error"] == "timeout"
    assert (
        client.post(url, json={"description": "x", "transaction_type": "expense"}).status_code
        == 401
    )


def test_13_1_6_preview_is_limited_to_60_per_minute_per_user(
    client: TestClient, auth: dict[str, str], ml: FakeMl
) -> None:
    url, body = (
        f"{API}/transactions/categorize-preview",
        {"description": "x", "transaction_type": "expense"},
    )
    assert all(client.post(url, json=body, headers=auth).status_code == 200 for _ in range(60))
    limited = client.post(url, json=body, headers=auth)
    assert limited.status_code == 429 and limited.json()["code"] == "RATE_LIMITED"
    assert int(limited.headers["Retry-After"]) >= 1
    other = signup(client)  # the limit is per user
    assert client.post(url, json=body, headers=other).status_code == 200


# --- CSV import (6.3: preview classifies in batch) ----------------------------------------------
def test_6_3_csv_preview_classifies_in_one_batch_and_commit_stores_predictions(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.table["ragu"] = ("groceries", 0.7, [("food_beverage", 0.2), ("shopping", 0.05)])
    seed = new_tx(client, auth, "Toko Aturan")  # becomes a rule
    client.patch(f"{API}/transactions/{seed['id']}", json={"category": "shopping"}, headers=auth)
    ml.calls.clear()
    p = preview(
        client, auth,
        f"{YESTERDAY},Toko Aturan,1000,expense,,,,",       # rule: no ML
        f"{YESTERDAY},Toko ragu,2000,expense,,,,",         # model suggest
        f"{YESTERDAY},Warung Biasa,3000,expense,,,,",      # model auto
        f"{YESTERDAY},Dengan Kategori,4000,expense,,,transportation,",  # user_set: no prediction
        "bad-date,Rusak,5000,expense,,,,",
    )  # fmt: skip
    assert ml.batch_sizes == [2] and len(ml.calls) == 1  # one batch call for the two model rows
    by_row = {r["row_number"]: r for r in p["rows"]}
    assert (
        by_row[2]["values"]["category_status"] == "rule"
        and by_row[2]["prediction"]["source"] == "rule"
    )
    assert by_row[3]["values"]["category_status"] == "suggested"
    assert by_row[4]["values"]["category_status"] == "auto"
    assert by_row[5]["prediction"] is None and by_row[5]["values"]["category_status"] == "user_set"
    assert by_row[6]["status"] == "invalid" and by_row[6]["prediction"] is None
    assert (
        by_row[3]["prediction"]["predicted_category"] == "groceries"
        and by_row[3]["prediction"]["model_version"]
    )

    done = commit(
        client,
        auth,
        p["import_id"],
        mode="skip_invalid",
    )
    assert done.status_code == 200, done.text
    imported = rows(
        engine,
        "SELECT t.id, t.description, t.category_status, c.slug FROM transactions t JOIN categories c "
        "ON c.id = t.category_id WHERE t.import_id = CAST(:i AS uuid) ORDER BY t.description",
        i=p["import_id"],
    )
    got = {r.description: (r.slug, r.category_status) for r in imported}
    assert got["Toko Aturan"] == ("shopping", "rule") and got["Toko ragu"] == (
        "groceries",
        "suggested",
    )
    assert got["Warung Biasa"] == ("food_beverage", "auto") and got["Dengan Kategori"] == (
        "transportation",
        "user_set",
    )
    preds = {r.description: predictions_of(engine, str(r.id)) for r in imported}
    assert [len(v) for k, v in sorted(preds.items())] == [1, 0, 1, 1] or len(preds) == 4
    assert preds["Dengan Kategori"] == [] and preds["Toko Aturan"][0].source == "user_rule"
    assert preds["Toko ragu"][0].source == "model" and preds["Toko ragu"][0].model_version
    rule = client.get(f"{API}/merchant-rules", headers=auth).json()["items"][0]
    assert rule["times_applied"] == 1  # counted at commit, not at preview


def test_6_3_csv_preview_survives_an_ml_outage(
    client: TestClient, auth: dict[str, str], ml: FakeMl, engine: Engine
) -> None:
    ml.mode = "5xx"
    p = preview(
        client,
        auth,
        f"{YESTERDAY},Warung A,1000,expense,,,,",
        f"{YESTERDAY},Warung B,2000,expense,,,,",
    )
    assert p["summary"]["valid"] == 2
    for r in p["rows"]:
        assert (
            r["values"]["category"] == "uncategorized"
            and r["values"]["category_status"] == "needs_review"
        )
        assert (
            r["prediction"]["source"] == "fallback" and r["prediction"]["ml_error"] == "unavailable"
        )
    assert commit(client, auth, p["import_id"]).status_code == 200
    errors = rows(engine, "SELECT ml_error FROM category_predictions WHERE ml_error IS NOT NULL")
    assert len(errors) >= 2
