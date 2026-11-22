"""FR-09 insights over HTTP (PRD 7.9, 13.2): refresh, upsert, dismiss, ordering, scoping."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.analytics import get_now
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
NOW = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.UTC)  # Friday 12:00 Jakarta; period Nov 1-30


def at(month: int, day: int, hour: int = 10) -> dt.datetime:
    return dt.datetime(2026, month, day, hour, tzinfo=JKT)


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    return signup(client)


def uid_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def seed_ledger(engine: Engine, user_id: uuid.UUID) -> None:
    rows: list[dict[str, Any]] = [
        # last period (Oct): first transaction on its first day, income, same-days food spend
        {
            "at": at(10, 1),
            "type": "expense",
            "amount": "300000",
            "category": "food_beverage",
            "merchant": "Resto Lama",
            "key": "resto-lama",
        },
        {"at": at(10, 5), "type": "income", "amount": "10000000", "category": "salary"},
        # this period to date: food doubles, one merchant dominates, many small buys, a queue
        *[
            {
                "at": at(11, d),
                "type": "expense",
                "amount": "50000",
                "category": "food_beverage",
                "merchant": "Warung A",
                "key": "warung-a",
            }
            for d in range(1, 7)
        ],
        *[
            {
                "at": at(11, 10 + i),
                "type": "expense",
                "amount": "100000",
                "category": "food_beverage",
                "merchant": f"Resto {i}",
                "key": f"resto-{i}",
            }
            for i in range(3)
        ],
        *[
            {
                "at": at(11, 1 + i),
                "type": "expense",
                "amount": "10000",
                "category": "transportation",
                "merchant": f"Angkot {i}",
                "key": f"angkot-{i}",
            }
            for i in range(15)
        ],
        *[
            {
                "at": at(11, 12 + i),
                "type": "expense",
                "amount": "20000",
                "category": "uncategorized",
                "merchant": f"Misc {i}",
                "key": f"misc-{i}",
                "status": "needs_review",
            }
            for i in range(5)
        ],
    ]
    seed_transactions(engine, user_id, rows)


def by_rule(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["rule_id"]: i for i in items}


def test_fr_09_01_refresh_creates_the_expected_insights_with_evidence(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    seed_ledger(engine, uid_of(client, auth))
    refreshed = client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    assert refreshed.status_code == 200, refreshed.text
    body = client.get(f"{API}/intelligence/insights", headers=auth).json()
    assert body["period_id"] == "2026-11-01"
    got = by_rule(body["items"])
    assert set(got) == {"INS-01", "INS-05", "INS-06", "INS-07", "INS-09"}
    assert refreshed.json() == {
        "period_id": "2026-11-01",
        "created": 5,
        "removed": 0,
        "total": 5,
    }

    food = got["INS-01"]
    assert food["severity"] == "warning" and food["subject_key"] == "food_beverage"
    assert food["message"] == (
        "Your Food & Beverage spending is up 100% compared with the same point last period"
    )
    m = food["evidence"]["metrics"]
    assert (m["current_to_date"], m["previous_same_days"], m["delta"]) == (
        "600000.00",
        "300000.00",
        "300000.00",
    )
    assert food["evidence"]["previous_period"] == {"start": "2026-10-01", "end": "2026-10-31"}
    assert food["rule_version"] == "1" and food["message_key"] == "insights.ins-01.up"

    assert got["INS-05"]["subject_key"] == "warung-a"
    assert got["INS-05"]["evidence"]["metrics"]["transactions"] == 6
    assert got["INS-06"]["evidence"]["metrics"]["small_count"] == 20
    assert got["INS-07"]["severity"] == "positive"
    assert got["INS-07"]["evidence"]["metrics"]["savings_rate_pct"] == "97.00"
    assert got["INS-09"]["evidence"]["metrics"]["review_queue"] == 5


def test_fr_09_03_refresh_twice_never_duplicates(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    seed_ledger(engine, uid_of(client, auth))
    app = client.app
    first = client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    app.state.rate_limiter = type(app.state.rate_limiter)()  # type: ignore[attr-defined]
    second = client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    assert first.json()["created"] == 5 and second.json()["created"] == 0
    assert second.json()["total"] == 5
    items = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    assert len(items) == 5 and len({(i["rule_id"], i["subject_key"]) for i in items}) == 5


def test_fr_09_05_order_is_warning_then_positive_then_info_and_limit_is_the_dashboard_card(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    seed_ledger(engine, uid_of(client, auth))
    client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    items = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    assert [i["severity"] for i in items][:2] == ["warning", "positive"]
    assert [float(i["priority"]) for i in items] == sorted(
        (float(i["priority"]) for i in items), reverse=True
    )
    top = client.get(f"{API}/intelligence/insights?limit=3", headers=auth).json()["items"]
    assert [i["rule_id"] for i in top] == [i["rule_id"] for i in items[:3]]


def test_fr_09_04_dismissed_insight_stays_dismissed_after_a_refresh(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    seed_ledger(engine, uid_of(client, auth))
    client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    items = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    target = by_rule(items)["INS-09"]
    done = client.post(f"{API}/intelligence/insights/{target['id']}/dismiss", headers=auth)
    assert done.status_code == 200 and done.json()["dismissed_at"] is not None

    client.app.state.rate_limiter = type(client.app.state.rate_limiter)()  # type: ignore[attr-defined]
    client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    visible = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    assert "INS-09" not in by_rule(visible)
    everything = client.get(
        f"{API}/intelligence/insights?include_dismissed=true", headers=auth
    ).json()["items"]
    again = by_rule(everything)["INS-09"]
    assert again["id"] == target["id"] and again["dismissed_at"] is not None
    # dismissing twice keeps the first timestamp
    twice = client.post(f"{API}/intelligence/insights/{target['id']}/dismiss", headers=auth)
    assert twice.json()["dismissed_at"] == done.json()["dismissed_at"]


def test_fr_09_insight_disappears_when_its_condition_no_longer_holds(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = uid_of(client, auth)
    seed_ledger(engine, uid)
    client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET category_status = 'user_set' WHERE user_id = :u"),
            {"u": uid},
        )
    client.app.state.rate_limiter = type(client.app.state.rate_limiter)()  # type: ignore[attr-defined]
    out = client.post(f"{API}/intelligence/insights/refresh", headers=auth).json()
    assert out["removed"] == 1 and out["total"] == 4
    items = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    assert "INS-09" not in by_rule(items)


def test_fr_09_01_refresh_is_rate_limited_to_once_a_minute(
    client: TestClient, auth: dict[str, str]
) -> None:
    assert client.post(f"{API}/intelligence/insights/refresh", headers=auth).status_code == 200
    blocked = client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers


def test_fr_09_other_users_insight_is_a_404_and_stays_untouched(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    seed_ledger(engine, uid_of(client, auth))
    client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    mine = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"][0]
    other = signup(client)
    assert client.get(f"{API}/intelligence/insights", headers=other).json()["items"] == []
    gone = client.post(f"{API}/intelligence/insights/{mine['id']}/dismiss", headers=other)
    assert gone.status_code == 404
    still = client.get(f"{API}/intelligence/insights", headers=auth).json()["items"]
    assert all(i["dismissed_at"] is None for i in still)


def test_fr_09_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{API}/intelligence/insights").status_code == 401
    assert client.post(f"{API}/intelligence/insights/refresh").status_code == 401


def test_fr_09_new_user_gets_no_insights_and_no_error(
    client: TestClient, auth: dict[str, str]
) -> None:
    out = client.post(f"{API}/intelligence/insights/refresh", headers=auth)
    assert out.status_code == 200 and out.json()["total"] == 0
