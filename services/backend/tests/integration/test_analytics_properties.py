"""Property tests: every dashboard figure equals a direct SQL computation (PRD 7.4, 26).

For 20 hypothesis-generated ledgers (time zones with and without DST, start days 1..28, transfers,
blank merchants, rows on both sides of every day boundary) each analytics endpoint is compared with
plain SQL that uses the local-date cast instead of the interval filter the service uses.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from app.api.analytics import get_now
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import configure_user, seed_transactions

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 11, 20, 6, 0, tzinfo=dt.UTC)
TIMEZONES = ["Asia/Jakarta", "UTC", "America/New_York", "Asia/Kolkata", "Pacific/Auckland"]
EXPENSE_CATEGORIES = ["food_beverage", "groceries", "transportation", "shopping", "housing"]
INCOME_CATEGORIES = ["salary", "freelance", "allowance"]
METHODS = ["cash", "e_wallet", "debit_card", "bank_transfer", "qris"]
MERCHANTS = ["Kopi Kenangan", "KOPI KENANGAN", "Grab", "Indomaret", "indomaret", "Warung", "", None]


@st.composite
def transactions(draw: st.DrawFn) -> list[dict[str, Any]]:
    # Unique minutes keep "the most recent merchant name" unambiguous.
    minutes = draw(st.lists(st.integers(-3 * 1440, 300 * 1440), max_size=45, unique=True))
    rows = []
    for minute in minutes:
        kind = draw(st.sampled_from(["expense", "expense", "expense", "income", "transfer"]))
        merchant = draw(st.sampled_from(MERCHANTS))
        category = {
            "expense": EXPENSE_CATEGORIES,
            "income": INCOME_CATEGORIES,
            "transfer": ["transfer"],
        }[kind]
        rows.append(
            {
                "at": NOW - dt.timedelta(minutes=minute),
                "type": kind,
                "amount": str(draw(st.decimals(Decimal("0.01"), Decimal("5000000"), places=2))),
                "category": draw(st.sampled_from(category)),
                "merchant": merchant,
                "key": (merchant or "").lower(),
                "method": draw(st.sampled_from(METHODS)),
            }
        )
    return rows


def sql_rows(engine: Engine, sql: str, **params: Any) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(text(sql), params))


LOCAL_DAY = "(t.transaction_date AT TIME ZONE :tz)::date BETWEEN :s AND :e"


def truth_flow(engine: Engine, uid: uuid.UUID, tz: str, s: str, e: str) -> tuple[Decimal, Decimal]:
    (row,) = sql_rows(
        engine,
        "SELECT COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'income'), 0), "
        "COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'expense'), 0) "
        f"FROM transactions t WHERE t.user_id = :u AND {LOCAL_DAY}",
        u=uid,
        tz=tz,
        s=s,
        e=e,
    )
    return Decimal(row[0]), Decimal(row[1])


def pct(n: Decimal, d: Decimal) -> str | None:
    return None if d == 0 else str((n * 100 / d).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def check_range(
    client: TestClient, engine: Engine, headers: dict[str, str], uid: uuid.UUID, tz: str, query: str
) -> None:
    summary = client.get(f"{API}/analytics/summary?{query}", headers=headers).json()
    s, e = summary["period"]["start"], summary["period"]["end"]
    income, expenses = truth_flow(engine, uid, tz, s, e)

    # FR-04.02..04: income, expenses, net, savings rate (transfers excluded by construction).
    assert Decimal(summary["income"]) == income, query
    assert Decimal(summary["expenses"]) == expenses, query
    assert Decimal(summary["net"]) == income - expenses, query
    assert summary["savings_rate"] == pct(income - expenses, income), query

    # FR-04.07: the comparison block recomputes from the same SQL over its own dates.
    cmp = summary["comparison"]
    for side in ("current", "previous"):
        inc, exp = truth_flow(engine, uid, tz, cmp[side]["start"], cmp[side]["end"])
        assert (Decimal(cmp[side]["income"]), Decimal(cmp[side]["expenses"])) == (inc, exp), side
        assert Decimal(cmp[side]["net"]) == inc - exp
    cur_net = Decimal(cmp["current"]["net"])
    prev_net = Decimal(cmp["previous"]["net"])
    prev_exp = Decimal(cmp["previous"]["expenses"])
    assert (cmp["change"]["expenses"] is None) == (prev_exp == 0)
    assert (cmp["change"]["net"] is None) == (prev_net == 0)
    if prev_net != 0:
        expected = ((cur_net - prev_net) * 100 / abs(prev_net)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        assert Decimal(cmp["change"]["net"]) == expected

    # FR-04.05: categories.
    cats = client.get(f"{API}/analytics/categories?{query}", headers=headers).json()
    truth = sql_rows(
        engine,
        "SELECT c.slug, SUM(t.amount), COUNT(*) FROM transactions t "
        "JOIN categories c ON c.id = t.category_id "
        f"WHERE t.user_id = :u AND t.transaction_type = 'expense' AND {LOCAL_DAY} "
        "GROUP BY c.slug",
        u=uid,
        tz=tz,
        s=s,
        e=e,
    )
    got = {i["slug"]: (Decimal(i["amount"]), i["count"], i["share"]) for i in cats["items"]}
    assert {k: (a, n) for k, (a, n, _) in got.items()} == {k: (Decimal(a), n) for k, a, n in truth}
    assert Decimal(cats["total_expenses"]) == expenses
    amounts = [Decimal(i["amount"]) for i in cats["items"]]
    assert amounts == sorted(amounts, reverse=True)
    for _, (amount, _, share) in got.items():
        assert share == pct(amount, expenses)

    # FR-04.08: top merchants (display name = the most recent spelling used for that key).
    merchants = client.get(f"{API}/analytics/merchants?{query}&limit=20", headers=headers).json()
    truth_m = sql_rows(
        engine,
        "SELECT merchant_key, SUM(amount), COUNT(*), "
        "(SELECT t2.merchant FROM transactions t2 WHERE t2.user_id = :u "
        " AND t2.merchant_key = t.merchant_key AND t2.transaction_type = 'expense' "
        " AND (t2.transaction_date AT TIME ZONE :tz)::date BETWEEN :s AND :e "
        " ORDER BY t2.transaction_date DESC LIMIT 1) "
        f"FROM transactions t WHERE t.user_id = :u AND t.transaction_type = 'expense' "
        f"AND t.merchant_key <> '' AND {LOCAL_DAY} GROUP BY t.merchant_key",
        u=uid,
        tz=tz,
        s=s,
        e=e,
    )
    expected_m = sorted(
        ((k, Decimal(a), n, name) for k, a, n, name in truth_m), key=lambda r: (-r[1], r[0])
    )[:20]
    assert [
        (i["merchant_key"], Decimal(i["amount"]), i["count"], i["name"]) for i in merchants["items"]
    ] == expected_m

    # FR-04.09: payment methods.
    methods = client.get(f"{API}/analytics/payment-methods?{query}", headers=headers).json()
    truth_p = sql_rows(
        engine,
        "SELECT payment_method, SUM(amount), COUNT(*) FROM transactions t "
        f"WHERE t.user_id = :u AND t.transaction_type = 'expense' AND {LOCAL_DAY} "
        "GROUP BY payment_method",
        u=uid,
        tz=tz,
        s=s,
        e=e,
    )
    assert {i["payment_method"]: (Decimal(i["amount"]), i["count"]) for i in methods["items"]} == {
        m: (Decimal(a), n) for m, a, n in truth_p
    }

    # FR-04.06: the daily trend is the SQL per-day sums, zero-filled, with a running total.
    days = (dt.date.fromisoformat(e) - dt.date.fromisoformat(s)).days + 1
    trend = client.get(f"{API}/analytics/trends?{query}&granularity=day", headers=headers).json()
    per_day = dict(
        sql_rows(
            engine,
            "SELECT (t.transaction_date AT TIME ZONE :tz)::date, SUM(t.amount) FROM transactions t "
            f"WHERE t.user_id = :u AND t.transaction_type = 'expense' AND {LOCAL_DAY} GROUP BY 1",
            u=uid,
            tz=tz,
            s=s,
            e=e,
        )
    )
    assert len(trend["series"]) == days
    running = Decimal("0")
    for point in trend["series"]:
        day = dt.date.fromisoformat(point["start"])
        running += Decimal(per_day.get(day, 0))
        assert Decimal(point["expenses"]) == Decimal(per_day.get(day, 0)), point
        if not point["future"]:
            assert Decimal(point["cumulative"]) == running, point
    assert running == expenses
    for g in ("week", "month"):
        coarse = client.get(
            f"{API}/analytics/trends?{query}&granularity={g}", headers=headers
        ).json()
        assert sum(Decimal(p["expenses"]) for p in coarse["series"]) == expenses, g


@st.composite
def scenarios(draw: st.DrawFn) -> dict[str, Any]:
    return {
        "tz": draw(st.sampled_from(TIMEZONES)),
        "start_day": draw(st.integers(1, 28)),
        "opening": draw(st.decimals(Decimal("0"), Decimal("1000000"), places=2)),
        "rows": draw(transactions()),
        "custom_start": draw(st.integers(0, 330)),
        "custom_len": draw(st.integers(1, 366)),
    }


@pytest.fixture
def owner(client: TestClient) -> tuple[dict[str, str], uuid.UUID]:
    """One user for the whole property run (registration is rate limited); rows are reset per example."""
    headers = signup(client)
    return headers, uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(scenario=scenarios())
def test_balance_equals_sql_ground_truth(
    client: TestClient,
    engine: Engine,
    owner: tuple[dict[str, str], uuid.UUID],
    scenario: dict[str, Any],
) -> None:
    """FR-04: for 20 generated ledgers every figure equals plain SQL (balance, flows, breakdowns)."""
    headers, uid = owner
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM transactions WHERE user_id = :u"), {"u": uid})
    tz = scenario["tz"]
    configure_user(
        engine,
        uid,
        timezone=tz,
        budget_period_start_day=scenario["start_day"],
        opening_balance=scenario["opening"],
    )
    seed_transactions(engine, uid, scenario["rows"])
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]

    # FR-04.01: balance = opening + all income - all expense up to now, transfers ignored.
    balance = client.get(f"{API}/analytics/summary", headers=headers).json()["balance"]
    (inc, exp) = sql_rows(
        engine,
        "SELECT COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'income'), 0), "
        "COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'expense'), 0) "
        "FROM transactions WHERE user_id = :u AND transaction_date <= :now",
        u=uid,
        now=NOW,
    )[0]
    assert Decimal(balance) == scenario["opening"] + Decimal(inc) - Decimal(exp)

    custom_from = dt.date(2025, 6, 1) + dt.timedelta(days=scenario["custom_start"])
    custom_to = custom_from + dt.timedelta(days=scenario["custom_len"] - 1)
    for query in (
        "range=current_period",
        "range=previous_period",
        "range=last_3_periods",
        f"range=custom&date_from={custom_from}&date_to={custom_to}",
    ):
        check_range(client, engine, headers, uid, tz, query)
