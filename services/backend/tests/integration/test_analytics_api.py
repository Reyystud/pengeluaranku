"""FR-04 analytics over HTTP: golden ledgers, ranges, validation and isolation (PRD 7.4, 13.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.api.analytics import get_now
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import (
    configure_user,
    seed_transactions,
    set_budget,
)

pytestmark = pytest.mark.integration

LEDGERS = Path(__file__).resolve().parents[1] / "fixtures" / "ledgers"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((LEDGERS / f"{name}.yaml").read_text(encoding="utf-8"))
    return data


def cases() -> list[Any]:
    out = []
    for path in sorted(LEDGERS.glob("*.yaml")):
        ledger = yaml.safe_load(path.read_text(encoding="utf-8"))
        for case in ledger["cases"]:
            out.append(pytest.param(ledger["name"], case, id=f"{ledger['name']}: {case['name']}"))
    return out


def user_id_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def pin_today(client: TestClient, now: dt.datetime) -> None:
    client.app.dependency_overrides[get_now] = lambda: now  # type: ignore[attr-defined]


def assert_subset(actual: Any, expected: Any, path: str = "") -> None:
    """``expected`` must be contained in ``actual``; lists must match element by element."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected an object, got {actual!r}"
        for key, value in expected.items():
            assert key in actual, f"{path}.{key} is missing in {sorted(actual)}"
            assert_subset(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), (
            f"{path}: expected {len(expected)} items, got "
            f"{len(actual) if isinstance(actual, list) else actual!r}"
        )
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            assert_subset(a, e, f"{path}[{i}]")
    else:
        assert actual == expected, f"{path}: expected {expected!r}, got {actual!r}"


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


def prepare(
    client: TestClient, engine: Engine, headers: dict[str, str], ledger: dict[str, Any]
) -> None:
    uid = user_id_of(client, headers)
    configure_user(engine, uid, **ledger["user"])
    seed_transactions(engine, uid, ledger["transactions"])
    if ledger.get("budget_limit"):
        set_budget(engine, uid, ledger["budget_limit"])
    pin_today(client, dt.datetime.fromisoformat(ledger["today"]))


@pytest.mark.parametrize(("ledger_name", "case"), cases())
def test_fr_04_golden_ledgers(
    client: TestClient,
    engine: Engine,
    auth: dict[str, str],
    ledger_name: str,
    case: dict[str, Any],
) -> None:
    ledger = load(ledger_name)
    prepare(client, engine, auth, ledger)
    r = client.get(f"{API}/analytics/{case['request']}", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert_subset(body, case["expect"])
    if "series_length" in case:
        assert len(body["series"]) == case["series_length"]
    for spot in case.get("spot", []):
        assert_subset(body["series"][spot["index"]], spot["expect"], f"series[{spot['index']}]")


def test_fr_04_money_is_a_string_never_a_float(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    prepare(client, engine, auth, load("basic_nov_2026"))
    body = client.get(f"{API}/analytics/summary", headers=auth).json()
    for key in ("balance", "income", "expenses", "net"):
        assert isinstance(body[key], str) and body[key].count(".") == 1, key
    assert isinstance(body["savings_rate"], str)  # percent as a string too


def test_transfer_excluded_from_income_and_expense(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    seed_transactions(
        engine,
        uid,
        [
            {"at": "2026-11-10T12:00:00+07:00", "type": "transfer", "amount": "999999.00", "category": "transfer", "key": "gopay", "merchant": "GoPay"},
            {"at": "2026-11-11T12:00:00+07:00", "type": "expense", "amount": "10000.00", "category": "food_beverage", "key": "warung", "merchant": "Warung"},
        ],
    )  # fmt: skip
    s = client.get(f"{API}/analytics/summary", headers=auth).json()
    assert (s["income"], s["expenses"], s["net"], s["balance"]) == (
        "0.00",
        "10000.00",
        "-10000.00",
        "-10000.00",
    )
    assert s["savings_rate"] is None  # no income
    cats = client.get(f"{API}/analytics/categories", headers=auth).json()
    assert [c["slug"] for c in cats["items"]] == ["food_beverage"]
    assert (
        client.get(f"{API}/analytics/merchants", headers=auth).json()["items"][0]["merchant_key"]
        == "warung"
    )
    methods = client.get(f"{API}/analytics/payment-methods", headers=auth).json()
    assert methods["total_expenses"] == "10000.00"


def test_fr_04_01_future_dated_rows_do_not_count_in_the_balance_yet(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    seed_transactions(
        engine,
        uid,
        [
            {"at": "2026-11-20T09:00:00+07:00", "type": "expense", "amount": "100.00", "category": "other_expense"},
            {"at": "2026-11-20T11:00:00+07:00", "type": "expense", "amount": "7.00", "category": "other_expense"},
        ],
    )  # fmt: skip
    # 03:00Z is 10:00 in Jakarta: the 11:00 row is still in the future.
    assert client.get(f"{API}/analytics/summary", headers=auth).json()["balance"] == "-100.00"


def test_fr_04_empty_user_gets_zeros_and_a_zero_filled_trend(
    client: TestClient, auth: dict[str, str]
) -> None:
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    s = client.get(f"{API}/analytics/summary", headers=auth).json()
    assert (s["balance"], s["income"], s["expenses"], s["net"]) == ("0.00",) * 3 + ("0.00",)
    assert s["savings_rate"] is None and s["comparison"]["change"] == {
        "income": None,
        "expenses": None,
        "net": None,
    }
    t = client.get(f"{API}/analytics/trends", headers=auth).json()
    assert len(t["series"]) == 30 and all(p["expenses"] == "0.00" for p in t["series"])
    assert t["budget_limit"] is None and all(p["budget_pace"] is None for p in t["series"])
    for path in ("categories", "merchants", "payment-methods"):
        assert client.get(f"{API}/analytics/{path}", headers=auth).json()["items"] == []


def test_fr_04_06_budget_pace_only_with_a_budget_and_a_single_period(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    without = client.get(f"{API}/analytics/trends", headers=auth).json()
    assert without["budget_limit"] is None
    set_budget(engine, uid, "3100000.00")
    with_budget = client.get(f"{API}/analytics/trends", headers=auth).json()
    assert with_budget["budget_limit"] == "3100000.00"
    paces = [p["budget_pace"] for p in with_budget["series"]]
    assert paces[0] == "103333.33" and paces[-1] == "3100000.00"  # limit x day_index / 30, 2 dp
    custom = client.get(
        f"{API}/analytics/trends?range=custom&date_from=2026-11-01&date_to=2026-11-10", headers=auth
    ).json()
    assert custom["budget_limit"] is None  # a custom range is not a budget period


def test_fr_04_05_review_queue_count_covers_suggested_and_needs_review(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    rows = [
        {"at": "2026-11-18T12:00:00+07:00", "type": "expense", "amount": "1.00", "category": "uncategorized", "status": status}
        for status in ("needs_review", "needs_review", "suggested", "auto", "rule", "user_set", "user_confirmed")
    ]  # fmt: skip
    seed_transactions(engine, uid, rows)
    assert client.get(f"{API}/analytics/summary", headers=auth).json()["review_queue_count"] == 3


def test_fr_04_10_start_day_change_applies_from_the_next_period(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    # Start day 1 now; changing to 15 takes effect on 2026-12-01 (the next period's start).
    configure_user(
        engine,
        uid,
        pending_period_start_day=15,
        pending_period_start_effective=dt.date(2026, 12, 1),
    )
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    cur = client.get(f"{API}/analytics/summary", headers=auth).json()["period"]
    assert (cur["start"], cur["end"]) == ("2026-11-01", "2026-11-30")  # unchanged
    pin_today(client, dt.datetime(2026, 12, 3, 3, 0, tzinfo=dt.UTC))
    transition = client.get(f"{API}/analytics/summary", headers=auth).json()["period"]
    assert (transition["start"], transition["end"]) == ("2026-12-01", "2026-12-14")
    pin_today(client, dt.datetime(2026, 12, 20, 3, 0, tzinfo=dt.UTC))
    after = client.get(f"{API}/analytics/summary", headers=auth).json()["period"]
    assert (after["start"], after["end"]) == ("2026-12-15", "2027-01-14")


def test_fr_04_timezone_decides_which_day_a_transaction_falls_on(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = user_id_of(client, auth)
    configure_user(engine, uid, timezone="America/New_York")
    pin_today(client, dt.datetime(2026, 11, 20, 18, 0, tzinfo=dt.UTC))
    # 03:30Z on Nov 1 is still Oct 31 evening in New York (UTC-4 on that date).
    seed_transactions(
        engine,
        uid,
        [
            {"at": "2026-11-01T03:30:00+00:00", "type": "expense", "amount": "10.00", "category": "other_expense"},
            {"at": "2026-11-01T05:30:00+00:00", "type": "expense", "amount": "20.00", "category": "other_expense"},
        ],
    )  # fmt: skip
    nov = client.get(f"{API}/analytics/summary", headers=auth).json()
    # Nov 1 00:00 in New York in November is already EDT/EST? DST ended Nov 1 2026 at 02:00 local,
    # so midnight is UTC-4 (04:00Z): the 03:30Z row is October, the 05:30Z row is November.
    assert nov["period"]["timezone"] == "America/New_York"
    assert nov["expenses"] == "20.00"
    prev = client.get(f"{API}/analytics/summary?range=previous_period", headers=auth).json()
    assert prev["expenses"] == "10.00"


# --- validation (13.1.5) -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "query",
    [
        "range=custom",
        "range=custom&date_from=2026-11-01",
        "range=custom&date_from=2026-11-10&date_to=2026-11-01",
        "range=custom&date_from=2025-01-01&date_to=2026-01-02",  # 367 days
        "range=current_period&date_from=2026-11-01&date_to=2026-11-10",
        "range=forever",
        "range=custom&date_from=nope&date_to=2026-11-10",
    ],
)
def test_fr_04_10_invalid_ranges_are_422(
    client: TestClient, auth: dict[str, str], query: str
) -> None:
    r = client.get(f"{API}/analytics/summary?{query}", headers=auth)
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")


def test_fr_04_10_a_custom_range_of_366_days_is_allowed(
    client: TestClient, auth: dict[str, str]
) -> None:
    ok = client.get(
        f"{API}/analytics/trends?range=custom&date_from=2025-01-01&date_to=2026-01-01", headers=auth
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["granularity"] == "month" and body["period"]["days_in_period"] == 366


@pytest.mark.parametrize(
    ("days", "expected"), [(62, "day"), (63, "week"), (183, "week"), (184, "month")]
)
def test_fr_04_10_granularity_auto_thresholds(
    client: TestClient, auth: dict[str, str], days: int, expected: str
) -> None:
    start = dt.date(2026, 1, 1)
    end = start + dt.timedelta(days=days - 1)
    r = client.get(
        f"{API}/analytics/trends?range=custom&date_from={start}&date_to={end}", headers=auth
    )
    assert r.json()["granularity"] == expected


def test_fr_04_08_merchant_limit_is_capped_at_20(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get(f"{API}/analytics/merchants?limit=20", headers=auth).status_code == 200
    for bad in (0, 21, -1, "x"):
        assert client.get(f"{API}/analytics/merchants?limit={bad}", headers=auth).status_code == 422


def test_fr_04_explicit_granularity_values(client: TestClient, auth: dict[str, str]) -> None:
    for g in ("auto", "day", "week", "month"):
        assert (
            client.get(f"{API}/analytics/trends?granularity={g}", headers=auth).status_code == 200
        )
    assert client.get(f"{API}/analytics/trends?granularity=year", headers=auth).status_code == 422


# --- security (0.3 rule 6, 17) -----------------------------------------------------------------
ENDPOINTS = ("summary", "categories", "trends", "merchants", "payment-methods")


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_fr_04_analytics_require_authentication(client: TestClient, endpoint: str) -> None:
    assert client.get(f"{API}/analytics/{endpoint}").status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.get(f"{API}/analytics/{endpoint}", headers=bad).status_code == 401


def test_fr_04_one_users_ledger_never_shows_in_another_users_numbers(
    client: TestClient, engine: Engine
) -> None:
    alice, bob = signup(client), signup(client)
    pin_today(client, dt.datetime(2026, 11, 20, 3, 0, tzinfo=dt.UTC))
    seed_transactions(
        engine,
        user_id_of(client, alice),
        [
            {"at": "2026-11-10T12:00:00+07:00", "type": "expense", "amount": "123456.00", "category": "food_beverage", "key": "secret shop", "merchant": "Secret Shop", "method": "cash"},
            {"at": "2026-11-11T12:00:00+07:00", "type": "income", "amount": "777.00", "category": "salary"},
        ],
    )  # fmt: skip
    for endpoint in ENDPOINTS:
        body = client.get(f"{API}/analytics/{endpoint}", headers=bob).text
        assert "123456" not in body and "Secret Shop" not in body and "777.00" not in body, endpoint
    assert client.get(f"{API}/analytics/summary", headers=alice).json()["expenses"] == "123456.00"


def test_fr_04_responses_are_documented_in_openapi(client: TestClient) -> None:
    spec = (
        client.get("/openapi.json").json()
        if client.get("/openapi.json").status_code == 200
        else client.app.openapi()
    )  # type: ignore[attr-defined]
    paths = [p for p in spec["paths"] if p.startswith(f"{API}/analytics/")]
    assert sorted(paths) == sorted(f"{API}/analytics/{e}" for e in ENDPOINTS)


def test_fr_12_analytics_repository_scopes_every_query_by_user_id(session: Any) -> None:
    """Every public method takes user_id first and sends it in its SQL (PRD 0.3 rule 6, 12.4)."""
    import inspect
    from zoneinfo import ZoneInfo

    from app.repositories.analytics import AnalyticsRepository, bounds_to_utc
    from sqlalchemy import event

    from tests.integration.conftest import make_user

    user = make_user(session)
    repo = AnalyticsRepository(session)
    tz = ZoneInfo("Asia/Jakarta")
    lo, hi = bounds_to_utc(dt.date(2026, 11, 1), dt.date(2026, 11, 30), tz)
    calls = {
        "flows_until": (hi,),
        "flows_between": (lo, hi),
        "category_breakdown": (lo, hi),
        "top_merchants": (lo, hi, 5),
        "payment_methods": (lo, hi),
        "expense_buckets": (tz, [(dt.date(2026, 11, 1), dt.date(2026, 11, 30))]),
        "review_queue_count": (),
        "overall_budget_limit": (),
    }
    public = {
        n
        for n, f in inspect.getmembers(AnalyticsRepository, inspect.isfunction)
        if not n.startswith("_")
    }
    assert public == set(calls), "add the new method to this test"
    for name in public:
        params = list(inspect.signature(getattr(AnalyticsRepository, name)).parameters)
        assert params[:2] == ["self", "user_id"], name

    seen: list[str] = []
    engine = session.get_bind()
    listener = lambda conn, cur, stmt, params, ctx, many: seen.append(stmt)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        for name, args in calls.items():
            seen.clear()
            getattr(repo, name)(user.id, *args)
            assert seen and all("user_id" in s for s in seen), (name, seen)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
