"""FR-07 period-end forecast over HTTP (PRD 7.7, 13.2): methods, minimum history, cache, bands."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.analytics import get_now
from app.models import User
from app.services.forecasts import ForecastService
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
NOW = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.UTC)  # Friday 12:00 in Jakarta, day 20 of Nov
OLD = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    return signup(client)


def pin(client: TestClient, when: dt.datetime) -> None:
    client.app.dependency_overrides[get_now] = lambda: when  # type: ignore[attr-defined]


def uid_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def day(n: int) -> dt.datetime:
    """10:00 Jakarta on 2026-11-``n`` (n may be <= 0 for earlier months)."""
    return dt.datetime(2026, 11, 1, 10, tzinfo=JKT) + dt.timedelta(days=n - 1)


def seed_days(
    engine: Engine, uid: uuid.UUID, first: int, last: int, amount: Any, category: str = "groceries"
) -> None:
    rows = []
    for n in range(first, last + 1):
        value = amount(day(n)) if callable(amount) else amount
        rows.append({"at": day(n), "type": "expense", "amount": str(value), "category": category,
                     "key": "toko"})  # fmt: skip
    seed_transactions(engine, uid, rows)
    with engine.begin() as conn:  # not "changed since" for the cache rule
        conn.execute(text("UPDATE transactions SET updated_at = :t WHERE user_id = :u"),
                     {"t": OLD, "u": uid})  # fmt: skip


def forecast(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    r = client.get(f"{API}/intelligence/forecast", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def stored(engine: Engine, uid: uuid.UUID) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text("SELECT count(*) FROM forecasts WHERE user_id = :u"), {"u": uid}
            ).scalar_one()
        )


# --- availability (7.7.2) ------------------------------------------------------------------------
def test_fr_07_02_no_transactions_needs_two_weeks(client: TestClient, auth: dict[str, str]) -> None:
    assert forecast(client, auth) == {
        "available": False,
        "reason": "INSUFFICIENT_HISTORY",
        "days_needed": 14,
        "transactions_needed": 0,
    }


def test_fr_07_02_ten_days_of_history_is_four_days_short(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_days(engine, uid_of(client, auth), 11, 20, 100_000)
    f = forecast(client, auth)
    assert (f["available"], f["days_needed"]) == (False, 4)
    assert stored(engine, uid_of(client, auth)) == 0  # nothing to cache


# --- limited history: run rate -------------------------------------------------------------------
def test_fr_07_02_twenty_days_gives_a_run_rate_estimate(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, 1, 20, 100_000)
    f = forecast(client, auth)
    assert f["available"] is True and f["method"] == "run_rate"
    assert f["history_level"] == "limited" and f["category"] is None
    assert f["spent_to_date"] == "2000000.00"
    assert f["predicted_remaining"] == "1000000.00" and f["predicted_total"] == "3000000.00"
    assert f["baseline_prediction"] == "3000000.00"
    assert f["expected_recurring_remaining"] == "0.00"
    assert f["interval_low"] == f["interval_high"] == "3000000.00"  # no variation in the history
    assert f["model_version"] == "run-rate-2" and f["budget"] is None
    p = f["period"]
    assert (p["start"], p["end"], p["days_elapsed"], p["days_in_period"]) == (
        "2026-11-01",
        "2026-11-30",
        20,
        30,
    )
    curve = f["daily_curve"]
    assert [c["date"] for c in curve][0] == "2026-11-21" and curve[-1]["date"] == "2026-11-30"
    assert len(curve) == 10 and curve[-1]["p50"] == "3000000.00"
    totals = [Decimal(c["p50"]) for c in curve]
    assert totals == sorted(totals)
    balance = Decimal(client.get(f"{API}/analytics/summary", headers=auth).json()["balance"])
    assert Decimal(f["estimated_period_end_balance"]) == balance - Decimal("1000000.00")


def test_fr_07_02_the_range_widens_when_spending_varies(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_days(engine, uid_of(client, auth), 1, 20, lambda d: 180_000 if d.day % 2 else 20_000)
    f = forecast(client, auth)
    low, mid, high = (Decimal(f[k]) for k in ("interval_low", "predicted_total", "interval_high"))
    assert mid == Decimal("3000000.00") and low < mid < high
    assert low >= Decimal(f["spent_to_date"])


# --- personal history: seasonal naive ------------------------------------------------------------
def test_fr_07_02_sixty_days_uses_same_weekday_averages(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    per_weekday = lambda d: 300_000 if d.weekday() >= 5 else 50_000  # noqa: E731
    seed_days(engine, uid, -49, 20, per_weekday)  # 70 days ending today
    f = forecast(client, auth)
    assert f["method"] == "seasonal_naive" and f["history_level"] == "personal"
    expected = sum(per_weekday(day(n)) for n in range(21, 31))
    assert Decimal(f["predicted_remaining"]) == Decimal(expected)
    assert Decimal(f["baseline_prediction"]) != Decimal(f["predicted_total"])  # run rate kept apart


# --- category forecasts (FR-07.01) ---------------------------------------------------------------
def test_fr_07_01_category_needs_sixty_days_and_twenty_transactions(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, 1, 20, 100_000)  # 20 days: overall ok, category not (needs 60 days)
    r = forecast(client, auth, category="groceries")
    assert (r["available"], r["days_needed"], r["transactions_needed"]) == (False, 40, 0)
    seed_days(engine, uid, -69, 0, 10_000, category="food_beverage")  # long, but 70 transactions
    seed_days(engine, uid, 1, 5, 10_000, category="transportation")  # only 5 transactions
    r = forecast(client, auth, category="transportation")
    assert (r["available"], r["transactions_needed"]) == (False, 15)
    g = forecast(client, auth, category="food_beverage")
    assert g["available"] is True and g["category"]["slug"] == "food_beverage"
    assert g["estimated_period_end_balance"] is None  # overall only
    assert g["method"] == "seasonal_naive"


@pytest.mark.parametrize(
    ("slug", "code"),
    [("nope", "UNKNOWN_CATEGORY"), ("salary", "CATEGORY_TYPE_MISMATCH")],
)
def test_fr_07_bad_category_is_422(
    client: TestClient, auth: dict[str, str], slug: str, code: str
) -> None:
    r = client.get(f"{API}/intelligence/forecast", params={"category": slug}, headers=auth)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == code


# --- budget band and projected status (FR-07.03, FR-05.07, 7.7.4) --------------------------------
def create_budget(client: TestClient, headers: dict[str, str], limit: str) -> dict[str, Any]:
    r = client.post(f"{API}/budgets", json={"limit_amount": limit}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ("limit", "band", "projected", "over"),
    [
        ("2500000", "high", "may_exceed", "500000.00"),
        ("3000000", "high", "may_exceed", "0.00"),  # L <= P50
        ("3100000", "medium", "may_exceed", "-100000.00"),  # P50 < L <= P90 (about 3.25M)
        ("3500000", "low", "on_track", "-500000.00"),
    ],
)
def test_fr_07_03_exceed_band_and_the_budget_projection(
    client: TestClient,
    auth: dict[str, str],
    engine: Engine,
    limit: str,
    band: str,
    projected: str,
    over: str,
) -> None:
    seed_days(engine, uid_of(client, auth), 1, 20, lambda d: 180_000 if d.day % 2 else 20_000)
    budget = create_budget(client, auth, limit)
    f = forecast(client, auth)
    assert f["budget"] == {
        "limit_amount": f"{Decimal(limit):.2f}",
        "predicted_over_budget": over,
        "exceed_band": band,
    }
    assert budget["projected"] == projected
    assert (
        client.get(f"{API}/budgets/{budget['id']}", headers=auth).json()["projected"] == projected
    )


def test_fr_05_07_projected_is_null_without_a_forecast(
    client: TestClient, auth: dict[str, str]
) -> None:
    assert create_budget(client, auth, "1000000")["projected"] is None


def test_fr_05_07_editing_the_limit_changes_the_projection(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed_days(engine, uid_of(client, auth), 1, 20, 100_000)
    b = create_budget(client, auth, "2800000")
    assert b["projected"] == "may_exceed"
    r = client.patch(f"{API}/budgets/{b['id']}", json={"limit_amount": "5000000"}, headers=auth)
    assert r.json()["projected"] == "on_track"


# --- cache (FR-07.07) ----------------------------------------------------------------------------
def test_fr_07_07_the_cached_forecast_is_reused_until_it_is_stale(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, 1, 20, 100_000)
    first = forecast(client, auth)
    assert stored(engine, uid) == 1
    assert forecast(client, auth)["generated_at"] == first["generated_at"]
    assert stored(engine, uid) == 1  # served from the cache

    # an edit, but the cache is younger than 6 h: still the cached one
    with engine.begin() as conn:
        conn.execute(text("UPDATE transactions SET updated_at = :t WHERE user_id = :u"),
                     {"t": NOW + dt.timedelta(hours=1), "u": uid})  # fmt: skip
    pin(client, NOW + dt.timedelta(hours=5))
    assert forecast(client, auth)["generated_at"] == first["generated_at"]

    # older than 6 h AND edited since: recomputed
    pin(client, NOW + dt.timedelta(hours=8))
    again = forecast(client, auth)
    assert again["generated_at"] != first["generated_at"] and stored(engine, uid) == 2

    # older than 6 h but nothing changed since: cached
    pin(client, NOW + dt.timedelta(hours=10))
    assert forecast(client, auth)["generated_at"] == again["generated_at"]


def test_fr_07_07_a_new_day_recomputes_because_the_remaining_days_changed(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, 1, 20, 100_000)
    first = forecast(client, auth)
    pin(client, NOW + dt.timedelta(days=1))
    second = forecast(client, auth)
    assert second["generated_at"] != first["generated_at"]
    assert (
        second["period"]["days_elapsed"] == 21 and second["daily_curve"][0]["date"] == "2026-11-22"
    )


def test_fr_07_07_only_the_newest_30_forecasts_per_series_are_kept(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, 1, 20, 100_000)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        for i in range(34):
            svc = ForecastService(s, user, NOW + dt.timedelta(minutes=i))
            svc.refresh(svc.analytics.period_of(svc.today), None)
        s.commit()
    assert stored(engine, uid) == 30
    with engine.connect() as conn:
        newest = conn.execute(
            text("SELECT max(as_of) FROM forecasts WHERE user_id = :u"), {"u": uid}
        ).scalar_one()
    assert newest == NOW + dt.timedelta(minutes=33)


def test_fr_07_the_daily_batch_forecasts_overall_and_every_eligible_category(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = uid_of(client, auth)
    seed_days(engine, uid, -69, 20, 10_000, category="food_beverage")
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert ForecastService(s, user, NOW).refresh_all() == 2  # overall + food_beverage
        s.commit()
    assert stored(engine, uid) == 2


# --- privacy -------------------------------------------------------------------------------------
def test_17_1_a_forecast_only_uses_the_callers_own_transactions(
    client: TestClient, engine: Engine
) -> None:
    alice = signup(client)
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    bob = signup(client)
    seed_days(engine, uid_of(client, alice), 1, 20, 100_000)
    assert forecast(client, alice)["available"] is True
    assert forecast(client, bob)["available"] is False
