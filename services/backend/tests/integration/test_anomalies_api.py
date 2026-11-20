"""FR-06 anomaly detection end to end: event path, alerts, feedback, API (PRD 7.6, 13.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from app.models import User
from app.repositories import AnomalyRepository, TransactionRepository
from app.services.anomalies import AnomalyService
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from ml.anomaly_detection import load_anomaly_config
from ml.anomaly_detection.history import build_history
from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions
from tests.integration.test_transactions_api import make, post_tx

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
CFG = load_anomaly_config()


def now() -> dt.datetime:
    return dt.datetime.now(JKT).replace(microsecond=0)


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


def user_id_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def seed_regular(engine: Engine, uid: uuid.UUID, n: int = 45, base: int = 40000) -> None:
    """``n`` ordinary Food & Beverage expenses, one every 36 hours, amounts within +-10%."""
    start = now()
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": start - dt.timedelta(hours=36 * (i + 1)),
                "type": "expense",
                "amount": str(round(base * (1 + ((i % 5) - 2) * 0.05))),
                "category": "food_beverage",
                "merchant": "Kopi Lama",
                "key": "kopi lama",
            }
            for i in range(n)
        ],
    )


def spike(
    client: TestClient,
    headers: dict[str, str],
    *,
    amount: str = "400000",
    description: str = "Warung Spike",
    days_ago: float = 0.05,
) -> dict[str, Any]:
    return make(
        client,
        headers,
        amount=amount,
        category="food_beverage",
        description=description,
        transaction_date=(now() - dt.timedelta(days=days_ago)).isoformat(),
    )


def anomalies(client: TestClient, headers: dict[str, str], **params: Any) -> list[dict[str, Any]]:
    r = client.get(f"{API}/intelligence/anomalies", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]  # type: ignore[no-any-return]


def alert_notes(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    items = client.get(f"{API}/notifications", params={"limit": 100}, headers=headers).json()
    return [n for n in items["items"] if n["type"] == "anomaly_alert"]


# --- detection through the event path ------------------------------------------------------------
def test_fr_06_01_a_large_expense_is_scored_when_it_is_saved(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    tx = spike(client, auth)
    (a,) = anomalies(client, auth)
    assert a["anomaly_type"] == "amount_spike" and a["severity"] == "high"
    assert a["status"] == "open" and a["is_alert"] is True and a["history_level"] == "personal"
    assert 0.5 <= a["score"] <= 1.0 and a["model_version"] == CFG.version
    assert a["transaction"]["id"] == tx["id"] and a["transaction"]["amount"] == "400000.00"
    assert a["category"]["slug"] == "food_beverage"
    codes = [r["code"] for r in a["reasons"]]
    assert codes[0] == "AMOUNT_VS_CATEGORY" and len(codes) <= CFG.max_reasons
    assert "Food & Beverage" in a["reasons"][0]["message"]
    (note,) = alert_notes(client, auth)  # FR-14: the alert is also a notification
    assert note["payload"]["anomaly_id"] == a["id"] and note["link"] == "/intelligence"
    detail = client.get(f"{API}/intelligence/anomalies/{a['id']}", headers=auth)
    assert detail.status_code == 200 and detail.json() == a


def test_fr_06_01_an_ordinary_expense_creates_nothing(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth, amount="42000", description="Warung Biasa")
    assert anomalies(client, auth) == [] and alert_notes(client, auth) == []


def test_fr_06_the_event_is_handled_once(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth)
    with engine.connect() as conn:
        done = conn.execute(
            text("SELECT count(*) FROM processed_events WHERE consumer = 'anomaly-scorer'")
        ).scalar_one()
        pending = conn.execute(
            text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
        ).scalar_one()
    assert done >= 1 and pending == 0
    spike(client, auth, amount="41000", description="Warung Biasa")  # next drain: no duplicate
    assert len(anomalies(client, auth)) == 1


def test_fr_06_04_income_and_transfers_are_never_scored(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    for kind, category in (("income", "salary"), ("transfer", "transfer")):
        make(client, auth, amount="9000000", transaction_type=kind, category=category,
             description=f"Big {kind}")  # fmt: skip
    assert anomalies(client, auth) == []


def test_fr_06_04_cold_start_stores_a_limited_anomaly_without_an_alert(
    client: TestClient, auth: dict[str, str]
) -> None:
    spike(client, auth, amount="5000000", description="Resto Baru")  # a brand-new account
    rows = anomalies(client, auth)
    assert {r["anomaly_type"] for r in rows} == {"amount_spike", "new_merchant_high_value"}
    for a in rows:
        assert a["history_level"] == "limited" and a["severity"] != "high"
        assert a["reasons"][-1]["code"] == "LIMITED_HISTORY"
        assert a["is_alert"] is False  # < 7 days of history
    assert alert_notes(client, auth) == []


def test_fr_06_04_a_user_with_history_but_few_in_the_category_is_limited_with_alerts(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = user_id_of(client, auth)
    start = now()
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": start - dt.timedelta(days=30 + i),
                "type": "expense",
                "amount": "40000",
                "category": "food_beverage",
                "key": "m",
            }
            for i in range(10)
        ],
    )
    spike(client, auth, amount="5000000")
    (a,) = anomalies(client, auth, type="amount_spike")
    assert a["history_level"] == "limited" and a["severity"] == "medium" and a["is_alert"] is True


def test_fr_06_03_alerts_are_capped_per_period_but_every_anomaly_is_stored(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    for i in range(CFG.alerts_per_period + 1):
        spike(client, auth, description=f"Warung {i}", days_ago=5 - i)
    rows = anomalies(client, auth, type="amount_spike", limit=50)
    assert len(rows) == CFG.alerts_per_period + 1
    assert sum(r["is_alert"] for r in rows) == CFG.alerts_per_period
    assert len(alert_notes(client, auth)) == CFG.alerts_per_period


def test_fr_06_old_transactions_are_historical_and_never_alert(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth, days_ago=CFG.alert_max_age_days + 3)  # e.g. a back-dated entry or an import
    (a,) = anomalies(client, auth)
    assert a["status"] == "historical" and a["is_alert"] is False
    assert alert_notes(client, auth) == []


# --- edit and delete (FR-06.07) ------------------------------------------------------------------
def test_fr_06_07_editing_a_transaction_replaces_its_anomaly(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    tx = spike(client, auth)
    assert len(anomalies(client, auth)) == 1
    r = client.patch(f"{API}/transactions/{tx['id']}", json={"amount": "41000"}, headers=auth)
    assert r.status_code == 200, r.text
    assert anomalies(client, auth) == []  # normal now
    old = anomalies(client, auth, status="superseded")
    assert len(old) == 1 and old[0]["is_alert"] is False
    r = client.patch(f"{API}/transactions/{tx['id']}", json={"amount": "600000"}, headers=auth)
    assert r.status_code == 200
    (again,) = anomalies(client, auth, type="amount_spike")
    assert again["id"] != old[0]["id"] and again["status"] == "open"


def test_fr_06_07_deleting_a_transaction_removes_its_anomaly(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    tx = spike(client, auth)
    assert client.delete(f"{API}/transactions/{tx['id']}", headers=auth).status_code == 204
    assert anomalies(client, auth, status=["open", "superseded", "historical"]) == []


# --- feedback (FR-06.04, FR-06.05) ---------------------------------------------------------------
def feedback(client: TestClient, headers: dict[str, str], aid: str, **body: Any) -> Any:
    return client.post(f"{API}/intelligence/anomalies/{aid}/feedback", json=body, headers=headers)


def test_fr_06_04_confirm_and_dismiss(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth, description="Warung A", days_ago=2)
    spike(client, auth, description="Warung B", days_ago=1)
    first, second = sorted(anomalies(client, auth), key=lambda a: a["created_at"])
    r = feedback(client, auth, first["id"], action="confirm")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert r.json()["feedback_at"] is not None and r.json()["feedback_reason"] is None
    r = feedback(client, auth, second["id"], action="dismiss", reason="wrong_amount")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["feedback_reason"]) == ("dismissed", "wrong_amount")
    assert r.json()["is_alert"] is False
    assert {a["status"] for a in anomalies(client, auth)} == {"confirmed", "dismissed"}
    assert [a["id"] for a in anomalies(client, auth, status="confirmed")] == [first["id"]]


def test_fr_06_04_feedback_validation(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth)
    (a,) = anomalies(client, auth)
    assert feedback(client, auth, a["id"], action="confirm", reason="other").status_code == 422
    assert feedback(client, auth, a["id"], action="dismiss", reason="nope").status_code == 422
    assert feedback(client, auth, a["id"], action="explode").status_code == 422
    assert feedback(client, auth, str(uuid.uuid4()), action="confirm").status_code == 404


def test_fr_06_07_feedback_on_a_replaced_anomaly_is_a_conflict(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    tx = spike(client, auth)
    (a,) = anomalies(client, auth)
    client.patch(f"{API}/transactions/{tx['id']}", json={"amount": "41000"}, headers=auth)
    r = feedback(client, auth, a["id"], action="confirm")
    assert r.status_code == 409 and r.json()["code"] == "ANOMALY_SUPERSEDED"


def test_fr_06_05_expected_purchase_suppresses_alerts_for_that_merchant(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth, description="Warung Hajatan", days_ago=3)
    (a,) = anomalies(client, auth)
    assert a["is_alert"] is True
    r = feedback(client, auth, a["id"], action="dismiss", reason="expected_purchase")
    assert r.status_code == 200
    spike(client, auth, description="Warung Hajatan", days_ago=1)
    again = [x for x in anomalies(client, auth) if x["status"] == "open"]
    assert len(again) == 1 and again[0]["is_alert"] is False  # stored, but no alert
    other = spike(client, auth, description="Warung Lain", days_ago=0.5)
    assert other["id"]
    lain = [x for x in anomalies(client, auth) if x["transaction"]["id"] == other["id"]]
    assert lain[0]["is_alert"] is True  # other merchants are unaffected
    with engine.connect() as conn:
        days = conn.execute(
            text(
                "SELECT extract(epoch FROM expires_at - now()) / 86400 "
                "FROM anomaly_suppressions WHERE user_id = :u"
            ),
            {"u": user_id_of(client, auth)},
        ).scalar_one()
    assert CFG.suppression_days - 0.1 < days <= CFG.suppression_days


def test_fr_06_05_other_dismiss_reasons_do_not_suppress(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    spike(client, auth, description="Warung Hajatan", days_ago=3)
    (a,) = anomalies(client, auth)
    feedback(client, auth, a["id"], action="dismiss", reason="other")
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM anomaly_suppressions WHERE user_id = :u"),
            {"u": user_id_of(client, auth)},
        ).scalar_one()
    assert count == 0


# --- listing (FR-06.08) --------------------------------------------------------------------------
def test_fr_06_08_filters_and_pagination(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    for i in range(3):
        spike(client, auth, description=f"Warung {i}", days_ago=4 - i)
    everything = anomalies(client, auth, limit=100)
    assert len(everything) == 3
    assert len(anomalies(client, auth, alerts_only=True)) == 3
    assert anomalies(client, auth, severity="low") == []
    assert len(anomalies(client, auth, severity="high")) == 3
    assert anomalies(client, auth, type="category_surge") == []
    period = everything[0]["period_id"]
    assert len(anomalies(client, auth, period_id=period)) == 3
    assert anomalies(client, auth, period_id="1999-01-01") == []
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get(f"{API}/intelligence/anomalies", params=params, headers=auth).json()
        seen += [a["id"] for a in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [a["id"] for a in everything]  # newest first, no gaps or repeats


def test_fr_06_08_a_bad_filter_is_a_422(client: TestClient, auth: dict[str, str]) -> None:
    for params in ({"severity": "extreme"}, {"type": "x"}, {"status": "gone"}, {"limit": 0}):
        r = client.get(f"{API}/intelligence/anomalies", params=params, headers=auth)
        assert r.status_code == 422, params


def test_17_1_anomalies_are_private_to_their_owner(client: TestClient, engine: Engine) -> None:
    alice, bob = signup(client), signup(client)
    seed_regular(engine, user_id_of(client, alice))
    spike(client, alice)
    (a,) = anomalies(client, alice)
    assert anomalies(client, bob) == []
    assert client.get(f"{API}/intelligence/anomalies/{a['id']}", headers=bob).status_code == 404
    assert feedback(client, bob, a["id"], action="confirm").status_code == 404
    assert anomalies(client, alice)[0]["status"] == "open"  # untouched


# --- resilience (PRD 6.3) ------------------------------------------------------------------------
def test_fr_06_a_scoring_failure_never_fails_the_write_and_is_retried(
    client: TestClient, auth: dict[str, str], engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_regular(engine, user_id_of(client, auth))
    real = AnomalyService.score_transaction

    def boom(self: AnomalyService, transaction_id: uuid.UUID) -> int:
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(AnomalyService, "score_transaction", boom)
    tx = spike(client, auth)  # saved, 201
    assert anomalies(client, auth) == []
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
            ).scalar_one()
            >= 1
        )
    monkeypatch.setattr(AnomalyService, "score_transaction", real)
    post_tx(client, auth, amount="41000", description="Warung Biasa")  # next write drains it
    assert [a["transaction"]["id"] for a in anomalies(client, auth)] == [tx["id"]]


# --- category surge (pattern anomaly, daily job in T-37) -----------------------------------------
def seed_weekly(engine: Engine, uid: uuid.UUID, today: dt.datetime, weekly: list[int]) -> None:
    """``weekly[0]`` is spent in the last 7 days, the rest in the weeks before it."""
    rows = []
    for w, total in enumerate(weekly):
        for d in range(2):  # two purchases per week
            rows.append(
                {
                    "at": today - dt.timedelta(days=7 * w + 1 + 2 * d),
                    "type": "expense",
                    "amount": str(total // 2),
                    "category": "groceries",
                    "key": f"toko{d}",
                }
            )
    seed_transactions(engine, uid, rows)


def test_fr_06_02_category_surge_is_stored_once_and_alerts(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = user_id_of(client, auth)
    today = now()
    seed_weekly(engine, uid, today, [900_000] + [300_000, 280_000, 320_000, 310_000] * 2)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert AnomalyService(s, user, today).detect_category_surges() == 1
        assert AnomalyService(s, user, today).detect_category_surges() == 0  # already open
        s.commit()
    (a,) = anomalies(client, auth)
    assert a["anomaly_type"] == "category_surge" and a["transaction"] is None
    assert a["category"]["slug"] == "groceries" and a["severity"] == "medium"
    assert a["reasons"][0]["code"] == "CATEGORY_SURGE" and a["is_alert"] is True
    assert len(alert_notes(client, auth)) == 1
    assert feedback(client, auth, a["id"], action="dismiss").status_code == 200


def test_fr_06_02_no_surge_for_a_normal_week(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = user_id_of(client, auth)
    today = now()
    seed_weekly(engine, uid, today, [320_000] + [300_000, 280_000, 320_000, 310_000] * 2)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert AnomalyService(s, user, today).detect_category_surges() == 0


# --- point in time and parity with the ML library -----------------------------------------------
def test_fr_06_history_is_point_in_time_and_matches_the_ml_library(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = user_id_of(client, auth)
    seed_regular(engine, uid, n=50)
    spike(client, auth, description="Toko Baru")
    with Session(engine) as s:
        repo = TransactionRepository(s)
        rows = repo.list(uid, limit=500)
        target = next(t for t in rows if t.description == "Toko Baru")
        sql = AnomalyRepository(s).history_for(
            uid, target, history_days=CFG.history_days, rate_days=CFG.burst_rate_days
        )
        frame = pd.DataFrame(
            [
                {
                    "occurred_at": t.transaction_date,
                    "created_at": t.created_at,
                    "type": t.transaction_type,
                    "amount": float(t.amount),
                    "category": str(t.category_id),
                    "merchant_key": t.merchant_key,
                }
                for t in rows
            ]
        )
        batch = build_history(
            frame, target.transaction_date, str(target.category_id), target.merchant_key, CFG
        )
    assert sorted(sql.category_amounts) == sorted(batch.category_amounts)
    assert sorted(sql.merchant_amounts) == sorted(batch.merchant_amounts)
    assert sql.merchant_seen == batch.merchant_seen is False
    assert sql.expense_count == batch.expense_count == 50
    assert (sql.category_count_24h, sql.category_count_rate_window) == (
        batch.category_count_24h,
        batch.category_count_rate_window,
    )
    assert sql.expense_p95 == pytest.approx(batch.expense_p95)
    assert sql.history_days == pytest.approx(batch.history_days, abs=1e-6)
    # Rows after the transaction never enter its history.
    seed_transactions(
        engine,
        uid,
        [
            {
                "at": target.transaction_date + dt.timedelta(hours=1 + i),
                "type": "expense",
                "amount": "99999999",
                "category": "food_beverage",
                "key": "toko baru",
            }
            for i in range(3)
        ],
    )
    with Session(engine) as s:
        t2 = TransactionRepository(s).get(uid, target.id)
        assert t2 is not None
        after = AnomalyRepository(s).history_for(
            uid, t2, history_days=CFG.history_days, rate_days=CFG.burst_rate_days
        )
    assert after == sql
