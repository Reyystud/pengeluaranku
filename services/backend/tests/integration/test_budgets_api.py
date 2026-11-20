"""FR-05 budgets and FR-14 notifications over HTTP (PRD 7.5, 7.14, 13.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.analytics import get_now
from app.models import User
from app.services.budgets import BudgetService
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions
from tests.integration.test_transactions_api import make

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


def spend(client: TestClient, headers: dict[str, str], amount: str, category: str | None = None,
          kind: str = "expense") -> dict[str, Any]:  # fmt: skip
    over: dict[str, Any] = {
        "amount": amount,
        "transaction_type": kind,
        "transaction_date": dt.datetime.now(JKT).replace(microsecond=0).isoformat(),
    }
    if category:
        over["category"] = category
    return make(client, headers, **over)


def create_budget(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    r = client.post(f"{API}/budgets", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def notes(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    r = client.get(f"{API}/notifications", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def thresholds_notified(client: TestClient, headers: dict[str, str]) -> list[int]:
    items = notes(client, headers, limit=100)["items"]
    return sorted(n["payload"]["threshold"] for n in items if n["type"] == "budget_threshold")


# --- CRUD and validation -------------------------------------------------------------------------
def test_fr_05_01_create_defaults_and_shape(client: TestClient, auth: dict[str, str]) -> None:
    b = create_budget(client, auth, category="groceries", limit_amount="500000")
    assert b["limit_amount"] == "500000.00" and b["alert_thresholds"] == [80, 100]
    assert b["category"]["slug"] == "groceries"
    assert (b["spent"], b["remaining"], b["utilization"], b["status"]) == (
        "0.00",
        "500000.00",
        "0.0",
        "healthy",
    )
    assert b["projected"] is None  # needs the forecast (T-24)
    p = b["period"]
    assert p["start"] <= p["end"] and p["period_id"] == p["start"] and 1 <= p["days_elapsed"] <= 31
    overall = create_budget(client, auth, limit_amount="2000000.50")
    assert overall["category"] is None
    listing = client.get(f"{API}/budgets", headers=auth).json()
    assert [i["category"] is None for i in listing["items"]] == [True, False]  # overall first
    assert listing["category_limits_exceed_overall"] is False


def test_fr_05_01_one_budget_per_category_and_one_overall(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, category="groceries", limit_amount="1")
    create_budget(client, auth, limit_amount="1")
    for body in ({"category": "groceries", "limit_amount": "5"}, {"limit_amount": "5"}):
        r = client.post(f"{API}/budgets", json=body, headers=auth)
        assert r.status_code == 409 and r.json()["code"] == "BUDGET_EXISTS", r.text


@pytest.mark.parametrize("slug", ["salary", "freelance", "transfer", "uncategorized"])
def test_fr_05_10_category_budget_on_a_non_expense_category_is_rejected(
    client: TestClient, auth: dict[str, str], slug: str
) -> None:
    r = client.post(f"{API}/budgets", json={"category": slug, "limit_amount": "5"}, headers=auth)
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0] == {
        "field": "category",
        "code": "CATEGORY_TYPE_MISMATCH",
        "message": "Budgets apply to expense categories only.",
    }


def test_fr_05_unknown_category_is_422(client: TestClient, auth: dict[str, str]) -> None:
    r = client.post(f"{API}/budgets", json={"category": "nope", "limit_amount": "5"}, headers=auth)
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "UNKNOWN_CATEGORY"


@pytest.mark.parametrize(
    "body",
    [
        {"limit_amount": "0"},
        {"limit_amount": "-5"},
        {"limit_amount": "1.005"},
        {"limit_amount": "99999999999999"},
        {"limit_amount": "abc"},
        {"limit_amount": "NaN"},
        {},
        {"limit_amount": "5", "alert_thresholds": [0]},
        {"limit_amount": "5", "alert_thresholds": [201]},
        {"limit_amount": "5", "alert_thresholds": list(range(1, 12))},
        {"limit_amount": "5", "alert_thresholds": ["x"]},
    ],
)
def test_fr_05_03_invalid_bodies_are_422(
    client: TestClient, auth: dict[str, str], body: dict[str, Any]
) -> None:
    r = client.post(f"{API}/budgets", json=body, headers=auth)
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")


def test_fr_05_05_thresholds_are_sorted_and_unique(
    client: TestClient, auth: dict[str, str]
) -> None:
    b = create_budget(client, auth, limit_amount="5", alert_thresholds=[100, 50, 100, 150])
    assert b["alert_thresholds"] == [50, 100, 150]
    none = client.patch(
        f"{API}/budgets/{b['id']}", json={"alert_thresholds": []}, headers=auth
    ).json()
    assert none["alert_thresholds"] == []  # no alerts is allowed


def test_fr_05_02_update_changes_limit_and_thresholds_only(
    client: TestClient, auth: dict[str, str]
) -> None:
    b = create_budget(client, auth, category="groceries", limit_amount="100")
    r = client.patch(
        f"{API}/budgets/{b['id']}",
        json={"limit_amount": "250.75", "alert_thresholds": [90]},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["limit_amount"], body["alert_thresholds"]) == ("250.75", [90])
    assert body["category"]["slug"] == "groceries" and body["updated_at"] >= b["updated_at"]
    for bad in ({"limit_amount": None}, {"alert_thresholds": None}, {"limit_amount": "0"}):
        assert client.patch(f"{API}/budgets/{b['id']}", json=bad, headers=auth).status_code == 422
    assert client.patch(f"{API}/budgets/{b['id']}", json={}, headers=auth).status_code == 200


def test_fr_05_02_delete_then_gone(client: TestClient, auth: dict[str, str]) -> None:
    b = create_budget(client, auth, limit_amount="100")
    assert client.delete(f"{API}/budgets/{b['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/budgets/{b['id']}", headers=auth).status_code == 404
    assert client.delete(f"{API}/budgets/{b['id']}", headers=auth).status_code == 404
    assert client.get(f"{API}/budgets", headers=auth).json()["items"] == []
    create_budget(client, auth, limit_amount="100")  # the slot is free again


# --- utilization and status ----------------------------------------------------------------------
def test_fr_05_03_spent_counts_only_expenses_of_the_category_in_the_period(
    client: TestClient, auth: dict[str, str]
) -> None:
    groceries = create_budget(client, auth, category="groceries", limit_amount="1000")
    overall = create_budget(client, auth, limit_amount="1000")
    spend(client, auth, "100", "groceries")
    spend(client, auth, "50", "food_beverage")
    spend(client, auth, "7")  # no category: uncategorized, still counts for the overall budget
    spend(client, auth, "999", "salary", kind="income")
    spend(client, auth, "999", "transfer", kind="transfer")
    by_id = {b["id"]: b for b in client.get(f"{API}/budgets", headers=auth).json()["items"]}
    assert by_id[groceries["id"]]["spent"] == "100.00"
    assert by_id[overall["id"]]["spent"] == "157.00"
    assert by_id[overall["id"]]["utilization"] == "15.7"
    assert by_id[overall["id"]]["remaining"] == "843.00"


def test_fr_05_03_other_periods_do_not_count(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = uuid.UUID(client.get(f"{API}/users/me", headers=auth).json()["id"])
    b = create_budget(client, auth, category="groceries", limit_amount="1000")
    seed_transactions(
        engine,
        uid,
        [
            {"at": dt.datetime.now(dt.UTC) - dt.timedelta(days=75), "type": "expense", "amount": "900", "category": "groceries"},
            {"at": dt.datetime.now(dt.UTC) - dt.timedelta(days=45), "type": "expense", "amount": "900", "category": "groceries"},
        ],
    )  # fmt: skip
    got = client.get(f"{API}/budgets/{b['id']}", headers=auth).json()
    assert got["spent"] == "0.00" and got["status"] == "healthy"


@pytest.mark.parametrize(
    ("amount", "utilization", "status"),
    [
        ("499.99", "50.0", "healthy"),  # 49.999 shows as 50.0, the status uses the exact value
        ("500", "50.0", "normal"),
        ("799", "79.9", "normal"),
        ("800", "80.0", "warning"),
        ("999.99", "100.0", "warning"),
        ("1000", "100.0", "exceeded"),
        ("2500", "250.0", "exceeded"),
    ],
)
def test_fr_05_04_status_boundaries(
    client: TestClient, auth: dict[str, str], amount: str, utilization: str, status: str
) -> None:
    b = create_budget(client, auth, category="groceries", limit_amount="1000")
    spend(client, auth, amount, "groceries")
    got = client.get(f"{API}/budgets/{b['id']}", headers=auth).json()
    assert (got["utilization"], got["status"]) == (utilization, status)


def test_fr_05_04_a_tiny_limit_and_a_huge_overspend_do_not_overflow(
    client: TestClient, auth: dict[str, str]
) -> None:
    b = create_budget(client, auth, category="groceries", limit_amount="0.01")
    spend(client, auth, "5000000", "groceries")
    got = client.get(f"{API}/budgets/{b['id']}", headers=auth).json()
    assert got["status"] == "exceeded" and got["utilization"] == "50000000000.0"
    assert got["remaining"] == "-4999999.99"


def test_fr_05_09_warns_when_category_limits_exceed_the_overall_limit(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, limit_amount="100")
    create_budget(client, auth, category="groceries", limit_amount="60")
    assert (
        client.get(f"{API}/budgets", headers=auth).json()["category_limits_exceed_overall"] is False
    )
    create_budget(client, auth, category="shopping", limit_amount="60")
    assert (
        client.get(f"{API}/budgets", headers=auth).json()["category_limits_exceed_overall"] is True
    )


# --- thresholds and notifications ----------------------------------------------------------------
def test_fr_05_05_crossing_a_threshold_notifies_once(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, category="groceries", limit_amount="100000")
    spend(client, auth, "50000", "groceries")
    assert thresholds_notified(client, auth) == []
    spend(client, auth, "35000", "groceries")  # 85%
    assert thresholds_notified(client, auth) == [80]
    spend(client, auth, "1000", "groceries")  # still between thresholds
    assert thresholds_notified(client, auth) == [80]
    spend(client, auth, "20000", "groceries")  # 106%
    assert thresholds_notified(client, auth) == [80, 100]
    spend(client, auth, "20000", "groceries")  # beyond: nothing new
    assert thresholds_notified(client, auth) == [80, 100]
    first = notes(client, auth)["items"][-1]
    assert first["type"] == "budget_threshold" and first["link"] == "/budgets"
    assert first["title"] == "Groceries budget at 80%"
    assert first["payload"]["category"] == "groceries"
    assert first["payload"]["limit_amount"] == "100000.00" and first["read_at"] is None


def test_fr_05_06_deleting_a_transaction_keeps_past_notifications_and_never_repeats_them(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, category="groceries", limit_amount="100")
    big = spend(client, auth, "150", "groceries")
    assert thresholds_notified(client, auth) == [80, 100]
    assert client.delete(f"{API}/transactions/{big['id']}", headers=auth).status_code == 204
    assert thresholds_notified(client, auth) == [80, 100]  # not removed
    spend(client, auth, "150", "groceries")  # crosses again in the same period
    assert len(notes(client, auth, limit=100)["items"]) == 2  # not duplicated


def test_fr_05_06_updates_bulk_actions_and_recategorization_are_evaluated(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, category="groceries", limit_amount="100", alert_thresholds=[50])
    a = spend(client, auth, "60", "food_beverage")
    assert thresholds_notified(client, auth) == []
    # update the category
    assert (
        client.patch(
            f"{API}/transactions/{a['id']}", json={"category": "groceries"}, headers=auth
        ).status_code
        == 200
    )
    assert thresholds_notified(client, auth) == [50]


def test_fr_05_06_bulk_categorize_is_evaluated(client: TestClient, auth: dict[str, str]) -> None:
    create_budget(client, auth, category="groceries", limit_amount="100", alert_thresholds=[50])
    ids = [spend(client, auth, "30", "food_beverage")["id"] for _ in range(2)]
    r = client.post(
        f"{API}/transactions/bulk-categorize",
        json={"ids": ids, "category": "groceries"},
        headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 200, r.text
    assert thresholds_notified(client, auth) == [50]


def test_fr_05_06_import_commit_is_evaluated(client: TestClient, auth: dict[str, str]) -> None:
    from tests.integration.test_imports_api import preview

    create_budget(client, auth, limit_amount="100", alert_thresholds=[50])
    day = (dt.datetime.now(JKT) - dt.timedelta(minutes=1)).date().isoformat()
    imp = preview(client, auth, f"{day},Supermarket run,600,expense,,,,")
    r = client.post(
        f"{API}/transactions/imports/{imp['import_id']}/commit",
        json={},
        headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 200, r.text
    assert thresholds_notified(client, auth) == [50]


def test_fr_05_02_lowering_the_limit_or_adding_a_threshold_notifies(
    client: TestClient, auth: dict[str, str]
) -> None:
    b = create_budget(client, auth, category="groceries", limit_amount="1000")
    spend(client, auth, "600", "groceries")
    assert thresholds_notified(client, auth) == []
    client.patch(f"{API}/budgets/{b['id']}", json={"limit_amount": "700"}, headers=auth)
    assert thresholds_notified(client, auth) == [80]  # 85.7%
    client.patch(f"{API}/budgets/{b['id']}", json={"alert_thresholds": [80, 85, 100]}, headers=auth)
    assert thresholds_notified(client, auth) == [80, 85]


def test_fr_05_05_creating_a_budget_that_is_already_exceeded_notifies_each_threshold(
    client: TestClient, auth: dict[str, str]
) -> None:
    spend(client, auth, "500", "groceries")
    create_budget(client, auth, category="groceries", limit_amount="100")
    assert thresholds_notified(client, auth) == [80, 100]


def test_fr_05_05_notifications_are_per_user(client: TestClient) -> None:
    alice, bob = signup(client), signup(client)
    create_budget(client, alice, category="groceries", limit_amount="100")
    create_budget(client, bob, category="groceries", limit_amount="100")
    spend(client, alice, "150", "groceries")
    assert thresholds_notified(client, alice) == [80, 100]
    assert thresholds_notified(client, bob) == []
    assert client.get(f"{API}/notifications/unread-count", headers=bob).json() == {"count": 0}


# --- notifications API ---------------------------------------------------------------------------
def test_fr_14_list_unread_count_read_and_read_all(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, category="groceries", limit_amount="100")
    create_budget(client, auth, category="shopping", limit_amount="100")
    spend(client, auth, "150", "groceries")
    spend(client, auth, "90", "shopping")
    assert client.get(f"{API}/notifications/unread-count", headers=auth).json() == {"count": 3}
    items = notes(client, auth)["items"]
    assert [n["created_at"] for n in items] == sorted(
        (n["created_at"] for n in items), reverse=True
    )
    one = client.post(f"{API}/notifications/{items[0]['id']}/read", headers=auth)
    assert one.status_code == 200 and one.json()["read_at"] is not None
    again = client.post(f"{API}/notifications/{items[0]['id']}/read", headers=auth).json()
    assert again["read_at"] == one.json()["read_at"]  # idempotent, timestamp unchanged
    assert client.get(f"{API}/notifications/unread-count", headers=auth).json() == {"count": 2}
    assert len(notes(client, auth, unread_only=True)["items"]) == 2
    done = client.post(f"{API}/notifications/read-all", headers=auth)
    assert done.json() == {"updated": 2}
    assert client.post(f"{API}/notifications/read-all", headers=auth).json() == {"updated": 0}
    assert notes(client, auth, unread_only=True)["items"] == []
    assert len(notes(client, auth)["items"]) == 3  # read ones stay in the list


def test_fr_14_pagination_walks_every_notification_once(
    client: TestClient, auth: dict[str, str]
) -> None:
    create_budget(client, auth, limit_amount="100", alert_thresholds=[1, 2, 3, 4, 5])
    spend(client, auth, "50")
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        page = notes(client, auth, limit=2, **({"cursor": cursor} if cursor else {}))
        seen += [n["id"] for n in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 5 and len(set(seen)) == 5
    assert client.get(f"{API}/notifications?cursor=garbage", headers=auth).status_code == 400
    for bad in ("limit=0", "limit=101"):
        assert client.get(f"{API}/notifications?{bad}", headers=auth).status_code == 422


def test_fr_14_a_cursor_from_another_user_is_rejected(client: TestClient) -> None:
    alice, bob = signup(client), signup(client)
    create_budget(client, alice, limit_amount="100", alert_thresholds=[1, 2, 3])
    spend(client, alice, "50")
    cursor = notes(client, alice, limit=1)["next_cursor"]
    assert cursor
    assert client.get(f"{API}/notifications?cursor={cursor}", headers=bob).status_code == 400


def test_fr_14_a_user_cannot_read_or_mark_anothers_notification(client: TestClient) -> None:
    alice, bob = signup(client), signup(client)
    create_budget(client, alice, limit_amount="100")
    spend(client, alice, "150")
    nid = notes(client, alice)["items"][0]["id"]
    assert client.post(f"{API}/notifications/{nid}/read", headers=bob).status_code == 404
    assert notes(client, alice, unread_only=True)["items"]  # untouched
    assert client.post(f"{API}/notifications/read-all", headers=bob).json() == {"updated": 0}
    assert client.get(f"{API}/notifications/unread-count", headers=alice).json()["count"] == 2


# --- history / snapshots -------------------------------------------------------------------------
def test_fr_05_08_snapshot_of_a_closed_period_feeds_the_history(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = uuid.UUID(client.get(f"{API}/users/me", headers=auth).json()["id"])
    b = create_budget(client, auth, category="groceries", limit_amount="1000")
    with engine.begin() as conn:  # the budget existed all of October
        conn.execute(
            text("UPDATE budgets SET created_at = '2026-10-01T00:00:00+00' WHERE id = :id"),
            {"id": b["id"]},
        )
    seed_transactions(
        engine,
        uid,
        [
            {"at": "2026-11-03T12:00:00+07:00", "type": "expense", "amount": "600.00", "category": "groceries"},
            {"at": "2026-11-20T12:00:00+07:00", "type": "expense", "amount": "250.00", "category": "groceries"},
            {"at": "2026-11-21T12:00:00+07:00", "type": "expense", "amount": "999.00", "category": "shopping"},
            {"at": "2026-12-02T12:00:00+07:00", "type": "expense", "amount": "5.00", "category": "groceries"},
        ],
    )  # fmt: skip
    now = dt.datetime(2026, 12, 2, 3, 0, tzinfo=dt.UTC)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert BudgetService(s, user, now).snapshot_closed_period() == 1
        assert BudgetService(s, user, now).snapshot_closed_period() == 0  # once per period
        s.commit()
    history = client.get(f"{API}/budgets/{b['id']}/history", headers=auth).json()["items"]
    assert history == [
        {
            "period_id": "2026-11-01",
            "limit_amount": "1000.00",
            "spent": "850.00",
            "utilization": "85.0",
        }
    ]
    # Raising the limit later does not rewrite what history says about November.
    client.patch(f"{API}/budgets/{b['id']}", json={"limit_amount": "5000"}, headers=auth)
    again = client.get(f"{API}/budgets/{b['id']}/history", headers=auth).json()["items"]
    assert again[0]["limit_amount"] == "1000.00"
    for bad in ("limit=0", "limit=61"):
        assert client.get(f"{API}/budgets/{b['id']}/history?{bad}", headers=auth).status_code == 422


def test_fr_05_08_a_budget_created_after_the_period_has_no_snapshot_for_it(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = uuid.UUID(client.get(f"{API}/users/me", headers=auth).json()["id"])
    create_budget(
        client, auth, limit_amount="1000"
    )  # created now, after Nov 2026 ended? no: before
    now = dt.datetime.now(dt.UTC) + dt.timedelta(days=70)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert BudgetService(s, user, now).snapshot_closed_period() == 1  # existed before the end
    far_past = dt.datetime.now(dt.UTC) - dt.timedelta(days=400)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        assert BudgetService(s, user, far_past).snapshot_closed_period() == 0  # did not exist yet


def test_fr_05_08_snapshots_of_a_zero_spend_period_and_a_huge_ratio_fit_the_column(
    client: TestClient, engine: Engine, auth: dict[str, str]
) -> None:
    uid = uuid.UUID(client.get(f"{API}/users/me", headers=auth).json()["id"])
    b = create_budget(client, auth, category="groceries", limit_amount="0.01")
    with engine.begin() as conn:
        conn.execute(text("UPDATE budgets SET created_at = '2026-01-01T00:00:00+00'"))
    seed_transactions(
        engine,
        uid,
        [{"at": "2026-11-03T12:00:00+07:00", "type": "expense", "amount": "9999999.00", "category": "groceries"}],
    )  # fmt: skip
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        BudgetService(s, user, dt.datetime(2026, 12, 5, tzinfo=dt.UTC)).snapshot_closed_period()
        s.commit()
    item = client.get(f"{API}/budgets/{b['id']}/history", headers=auth).json()["items"][0]
    assert Decimal(item["utilization"]) == Decimal(
        "100000.0"
    )  # clamped at 999.9999 (x 100, rounded)


# --- security ------------------------------------------------------------------------------------
ENDPOINTS = [
    ("GET", "/budgets"),
    ("POST", "/budgets"),
    ("GET", "/notifications"),
    ("GET", "/notifications/unread-count"),
    ("POST", "/notifications/read-all"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_fr_05_endpoints_require_authentication(client: TestClient, method: str, path: str) -> None:
    assert client.request(method, f"{API}{path}", json={}).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert client.request(method, f"{API}{path}", json={}, headers=bad).status_code == 401


def test_fr_05_budgets_of_one_user_are_invisible_to_another(client: TestClient) -> None:
    alice, bob = signup(client), signup(client)
    b = create_budget(client, alice, category="groceries", limit_amount="123456")
    assert client.get(f"{API}/budgets", headers=bob).json()["items"] == []
    assert "123456" not in client.get(f"{API}/budgets/{b['id']}", headers=bob).text
    create_budget(client, bob, category="groceries", limit_amount="1")  # no cross-user 409


def test_fr_05_the_clock_is_a_dependency_so_the_period_follows_today(
    client: TestClient, auth: dict[str, str]
) -> None:
    client.app.dependency_overrides[get_now] = lambda: dt.datetime(2026, 2, 15, 3, 0, tzinfo=dt.UTC)  # type: ignore[attr-defined]
    b = create_budget(client, auth, limit_amount="1000")
    assert (b["period"]["start"], b["period"]["end"], b["period"]["days_elapsed"]) == (
        "2026-02-01",
        "2026-02-28",
        15,
    )


def test_fr_05_05_create_once_reports_whether_it_inserted(session: Session) -> None:
    from app.repositories import NotificationRepository

    from tests.integration.conftest import make_user

    user = make_user(session)
    repo = NotificationRepository(session)
    args: dict[str, Any] = {
        "type": "budget_threshold",
        "title": "t",
        "body": "b",
        "link": None,
        "payload": {},
    }
    assert repo.create_once(user.id, dedupe_key="k", **args) is True
    assert repo.create_once(user.id, dedupe_key="k", **args) is False
    assert repo.create_once(user.id, dedupe_key="k2", **args) is True
    assert repo.unread_count(user.id) == 2


def test_fr_12_budget_and_notification_repositories_filter_every_query_by_user_id(
    session: Session,
) -> None:
    import inspect

    from app.repositories import BudgetRepository, NotificationRepository
    from sqlalchemy import event

    from tests.integration.conftest import make_user

    user = make_user(session)
    lo = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    hi = lo + dt.timedelta(days=30)
    nil = uuid.uuid4()
    calls: list[tuple[Any, str, tuple[Any, ...], dict[str, Any]]] = [
        (BudgetRepository, "list_all", (), {}),
        (BudgetRepository, "get_for_category", (None,), {}),
        (BudgetRepository, "spent_by_category", (lo, hi), {}),
        (BudgetRepository, "snapshots", (nil, 5), {}),
        (
            BudgetRepository,
            "write_snapshot",
            (nil, lo.date(), Decimal(1), Decimal(1), Decimal(1)),
            {},
        ),
        (NotificationRepository, "page", (), {"unread_only": True, "limit": 5, "after": None}),
        (NotificationRepository, "unread_count", (), {}),
        (NotificationRepository, "mark_all_read", (), {}),
    ]
    covered = {(c.__name__, n) for c, n, _, _ in calls} | {
        ("NotificationRepository", "create_once")
    }
    for cls in (BudgetRepository, NotificationRepository):
        own = {
            n
            for n, f in inspect.getmembers(cls, inspect.isfunction)
            if not n.startswith("_") and f.__qualname__.startswith(cls.__name__)
        }
        assert {(cls.__name__, n) for n in own} <= covered, "add the new method to this test"
        for n in own:
            assert list(inspect.signature(getattr(cls, n)).parameters)[:2] == ["self", "user_id"]
    seen: list[str] = []
    engine = session.get_bind()
    listener = lambda conn, cur, stmt, params, ctx, many: seen.append(stmt)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        for cls, name, args, kwargs in calls:
            seen.clear()
            if name == "write_snapshot":
                continue  # needs a real budget row (FK); covered through the API tests
            getattr(cls(session), name)(user.id, *args, **kwargs)
            assert seen and all("user_id" in s for s in seen), (name, seen)
    finally:
        event.remove(engine, "before_cursor_execute", listener)
