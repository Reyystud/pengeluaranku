"""FR-08 recurring series over HTTP (PRD 7.8, 13.2) and the forecast decomposition (7.7.1)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.api.analytics import get_now
from app.models import User
from app.services.forecasts import ForecastService
from app.services.recurring import RecurringService
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from tests.integration.conftest import API, signup
from tests.integration.ledger_support import seed_transactions

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")
NOW = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.UTC)  # Friday 12:00 Jakarta, day 20 of Nov
OLD = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    return signup(client)


def uid_of(client: TestClient, headers: dict[str, str]) -> uuid.UUID:
    return uuid.UUID(client.get(f"{API}/users/me", headers=headers).json()["id"])


def at(month: int, day: int) -> dt.datetime:
    return dt.datetime(2026, month, day, 10, tzinfo=JKT)


def monthly(
    key: str,
    amounts: list[str],
    *,
    day: int,
    last_month: int,
    category: str = "entertainment",
    kind: str = "expense",
    display: str | None = None,
) -> list[dict[str, Any]]:
    """One row per month, ending in ``last_month`` of 2026, with the given amounts."""
    first = last_month - len(amounts) + 1
    return [
        {
            "at": at(first + i, day),
            "type": kind,
            "amount": amount,
            "category": category,
            "key": key,
            "merchant": display or key.title(),
        }
        for i, amount in enumerate(amounts)
    ]


def seed(engine: Engine, client: TestClient, headers: dict[str, str], rows: list[dict[str, Any]]):
    uid = uid_of(client, headers)
    seed_transactions(engine, uid, rows)
    with engine.begin() as conn:  # not "changed since" for the forecast cache rule
        conn.execute(text("UPDATE transactions SET updated_at = :t WHERE user_id = :u"),
                     {"t": OLD, "u": uid})  # fmt: skip
    return uid


def recurring(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    r = client.get(f"{API}/intelligence/recurring", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def by_key(listing: dict[str, Any], key: str) -> dict[str, Any]:
    return next(i for i in listing["items"] if i["merchant_key"] == key)


def ledger() -> list[dict[str, Any]]:
    return [
        *monthly("netflix", ["54000"] * 6, day=5, last_month=11),  # last paid Nov 5
        *monthly("spotify", ["59000"] * 5, day=25, last_month=10),  # next ~Nov 25
        *monthly(
            "gaji pt maju", ["8000000"] * 5, day=25, last_month=10, category="salary", kind="income"
        ),  # fmt: skip
    ]


# --- list (FR-08.01, 08.02, 08.04) ---------------------------------------------------------------
def test_fr_08_04_empty_ledger_has_no_series(client: TestClient, auth: dict[str, str]) -> None:
    listing = recurring(client, auth)
    assert listing["items"] == [] and listing["upcoming"] == []
    assert listing["monthly_expense_total"] == "0.00" and listing["monthly_income_total"] == "0.00"


def test_fr_08_02_series_carry_their_detected_fields(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    netflix = by_key(recurring(client, auth), "netflix")
    assert netflix["frequency"] == "monthly" and netflix["transaction_type"] == "expense"
    assert netflix["category"]["slug"] == "entertainment"
    assert netflix["expected_amount"] == netflix["effective_amount"] == "54000.00"
    assert netflix["user_expected_amount"] is None and netflix["monthly_equivalent"] == "54000.00"
    assert (netflix["occurrences"], netflix["amount_cv"], netflix["confidence"]) == (6, 0.0, 1.0)
    assert netflix["last_date"] == "2026-11-05" and netflix["next_expected_date"] == "2026-12-06"
    assert netflix["status"] == "active" and netflix["amount_change"] is None
    assert netflix["merchant_display"] == "Netflix"


def test_fr_08_04_sorted_by_next_due_with_monthly_totals_and_upcoming(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    listing = recurring(client, auth)
    dates = [i["next_expected_date"] for i in listing["items"]]
    assert dates == sorted(dates) and len(dates) == 3
    assert listing["monthly_expense_total"] == "113000.00"  # 54,000 + 59,000
    assert listing["monthly_income_total"] == "8000000.00"
    # due within 7 days of Nov 20: spotify and the salary (Nov 25), not netflix (Dec 6)
    assert sorted(i["merchant_key"] for i in listing["upcoming"]) == ["gaji pt maju", "spotify"]


def test_fr_08_01_income_is_listed_as_income(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    gaji = by_key(recurring(client, auth), "gaji pt maju")
    assert gaji["transaction_type"] == "income" and gaji["category"]["slug"] == "salary"


def test_fr_08_03_a_price_change_is_reported_with_both_amounts(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, monthly("netflix", ["54000"] * 5 + ["65000"], day=5, last_month=11))
    netflix = by_key(recurring(client, auth), "netflix")
    assert netflix["amount_change"] == {"previous_amount": "54000.00", "latest_amount": "65000.00"}


def test_fr_08_a_merchant_without_a_key_or_with_a_one_off_pattern_is_not_a_series(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = monthly("", ["50000"] * 5, day=5, last_month=11)
    rows += monthly("sekali", ["50000"] * 2, day=5, last_month=11)
    seed(engine, client, auth, rows)
    assert recurring(client, auth)["items"] == []


def test_fr_08_series_that_stop_paying_become_paused_then_ended(
    client: TestClient, engine: Engine
) -> None:
    headers = signup(client)
    seed(engine, client, headers, monthly("netflix", ["54000"] * 5, day=5, last_month=7))
    states = {}
    for label, when in (("paused", dt.datetime(2026, 9, 20, tzinfo=dt.UTC)),
                        ("ended", dt.datetime(2026, 11, 20, tzinfo=dt.UTC))):  # fmt: skip
        client.app.dependency_overrides[get_now] = lambda when=when: when  # type: ignore[attr-defined]
        states[label] = by_key(recurring(client, headers), "netflix")["status"]
    assert states == {"paused": "paused", "ended": "ended"}


def test_fr_08_series_stay_out_of_the_totals_once_ended(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, monthly("netflix", ["54000"] * 5, day=5, last_month=6))
    listing = recurring(client, auth)
    assert by_key(listing, "netflix")["status"] == "ended"
    assert listing["monthly_expense_total"] == "0.00" and listing["upcoming"] == []


def test_fr_08_detection_is_idempotent_and_keeps_series_ids(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    first = recurring(client, auth)
    second = recurring(client, auth)
    assert [i["id"] for i in first["items"]] == [i["id"] for i in second["items"]]
    with engine.connect() as conn:
        links = conn.execute(
            text("SELECT count(*) FROM recurring_series_transactions")
        ).scalar_one()
    assert links >= 16


# --- user decisions (FR-08.05) -------------------------------------------------------------------
def patch(client: TestClient, headers: dict[str, str], series_id: str, body: dict[str, Any]) -> Any:
    return client.patch(f"{API}/intelligence/recurring/{series_id}", json=body, headers=headers)


def test_fr_08_05_confirm_survives_recomputation(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    series = by_key(recurring(client, auth), "netflix")
    r = patch(client, auth, series["id"], {"status": "user_confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "user_confirmed"
    assert by_key(recurring(client, auth), "netflix")["status"] == "user_confirmed"


def test_fr_08_05_reject_hides_the_series_and_it_is_never_suggested_again(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = seed(engine, client, auth, ledger())
    series = by_key(recurring(client, auth), "netflix")
    assert patch(client, auth, series["id"], {"status": "user_rejected"}).status_code == 200
    for _ in range(2):
        listing = recurring(client, auth)
        assert "netflix" not in [i["merchant_key"] for i in listing["items"]]
    assert listing["monthly_expense_total"] == "59000.00"
    with engine.connect() as conn:
        status = conn.execute(
            text(
                "SELECT status FROM recurring_series WHERE user_id = :u AND merchant_key = 'netflix'"
            ),
            {"u": uid},
        ).scalar_one()
    assert status == "user_rejected"


def test_fr_08_05_edit_the_expected_amount_and_clear_it(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    seed(engine, client, auth, ledger())
    series = by_key(recurring(client, auth), "netflix")
    edited = patch(client, auth, series["id"], {"user_expected_amount": "60000.00"}).json()
    assert edited["user_expected_amount"] == "60000.00"
    assert edited["effective_amount"] == "60000.00" and edited["expected_amount"] == "54000.00"
    assert recurring(client, auth)["monthly_expense_total"] == "119000.00"  # 60,000 + 59,000
    cleared = patch(client, auth, series["id"], {"user_expected_amount": None}).json()
    assert cleared["user_expected_amount"] is None and cleared["effective_amount"] == "54000.00"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": "active"},
        {"status": "user_confirmed", "extra": 1},
        {"user_expected_amount": "0"},
        {"user_expected_amount": "-5"},
        {"user_expected_amount": "12.345"},
        {"user_expected_amount": "99999999999999"},
    ],
)
def test_fr_08_05_invalid_patches_are_422(
    client: TestClient, auth: dict[str, str], engine: Engine, body: dict[str, Any]
) -> None:
    seed(engine, client, auth, ledger())
    series = by_key(recurring(client, auth), "netflix")
    assert patch(client, auth, series["id"], body).status_code == 422


def test_fr_08_05_unknown_series_is_404(client: TestClient, auth: dict[str, str]) -> None:
    assert patch(client, auth, str(uuid.uuid4()), {"status": "user_confirmed"}).status_code == 404


def test_fr_08_series_that_no_longer_qualify_are_dropped_unless_confirmed(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = seed(engine, client, auth, ledger())
    listing = recurring(client, auth)
    patch(client, auth, by_key(listing, "spotify")["id"], {"status": "user_confirmed"})
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM transactions WHERE user_id = :u AND merchant_key IN ('netflix', 'spotify')"
            ),
            {"u": uid},
        )
    keys = sorted(i["merchant_key"] for i in recurring(client, auth)["items"])
    assert keys == [
        "gaji pt maju",
        "spotify",
    ]  # netflix (automatic) goes, spotify (confirmed) stays


# --- privacy (17.1, 0.3 rule 6) ------------------------------------------------------------------
def test_17_1_series_are_private_to_their_owner(client: TestClient, engine: Engine) -> None:
    client.app.dependency_overrides[get_now] = lambda: NOW  # type: ignore[attr-defined]
    alice, bob = signup(client), signup(client)
    seed(engine, client, alice, ledger())
    mine = by_key(recurring(client, alice), "netflix")
    assert recurring(client, bob)["items"] == []
    assert patch(client, bob, mine["id"], {"status": "user_rejected"}).status_code == 404
    assert by_key(recurring(client, alice), "netflix")["status"] == "active"


def test_17_1_recurring_requires_authentication(client: TestClient) -> None:
    assert client.get(f"{API}/intelligence/recurring").status_code == 401


# --- FR-08.06 event path ------------------------------------------------------------------------
def test_fr_08_06_a_new_charge_of_a_known_merchant_refreshes_only_that_series(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = seed(
        engine, client, auth, ledger() + monthly("hulu", ["70000"] * 4, day=3, last_month=11)
    )
    recurring(client, auth)  # series exist now
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM recurring_series WHERE user_id = :u AND merchant_key = 'hulu'"),
            {"u": uid},
        )
    new = monthly("spotify", ["59000"], day=25, last_month=11)
    seed_transactions(engine, uid, new)
    with Session(engine) as s:
        user = s.get(User, uid)
        assert user is not None
        ids = {
            row[0]
            for row in s.execute(
                text("SELECT id FROM transactions WHERE user_id = :u AND transaction_date >= :d"),
                {"u": uid, "d": at(11, 25)},
            )
        }
        service = RecurringService(s, user, at(11, 26))
        service.refresh_for_transactions(ids)
        s.commit()
    with engine.connect() as conn:
        rows = {
            key: (last, n)
            for key, last, n in conn.execute(
                text(
                    "SELECT merchant_key, last_date, occurrences FROM recurring_series "
                    "WHERE user_id = :u"
                ),
                {"u": uid},
            )
        }
    assert rows["spotify"] == (dt.date(2026, 11, 25), 6)
    assert "hulu" not in rows  # unknown merchants are found by the nightly/lazy detection only


def test_fr_08_06_saving_a_known_merchants_charge_updates_its_series_through_the_event_path(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    uid = seed(engine, client, auth, monthly("netflix", ["54000"] * 5, day=5, last_month=10))
    assert by_key(recurring(client, auth), "netflix")["occurrences"] == 5
    created = client.post(
        f"{API}/transactions",
        json={
            "transaction_type": "expense",
            "amount": "54000.00",
            "description": "Netflix November",
            "merchant": "Netflix",
            "transaction_date": "2026-11-05T10:00:00+07:00",
            "category": "entertainment",
        },
        headers={**auth, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert created.status_code == 201, created.text
    with engine.connect() as conn:  # no GET in between: the event consumer did this
        last, count = conn.execute(
            text(
                "SELECT last_date, occurrences FROM recurring_series "
                "WHERE user_id = :u AND merchant_key = 'netflix'"
            ),
            {"u": uid},
        ).one()
    assert (last, count) == (dt.date(2026, 11, 5), 6)


# --- forecast decomposition (7.7.1, FR-07.04) ---------------------------------------------------
def daily(
    key: str, first: dt.date, last: dt.date, amount: str, category: str
) -> list[dict[str, Any]]:
    out = []
    day = first
    while day <= last:
        out.append(
            {
                "at": dt.datetime.combine(day, dt.time(10), tzinfo=JKT),
                "type": "expense",
                "amount": amount,
                "category": category,
                "key": key,
            }  # fmt: skip
        )
        day += dt.timedelta(days=1)
    return out


def forecast(client: TestClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    r = client.get(f"{API}/intelligence/forecast", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_fr_07_01_recurring_charges_still_to_come_are_added_not_averaged(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = daily("toko", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "100000", "groceries")
    rows += monthly("spotify", ["59000"] * 5, day=25, last_month=10)  # next due Nov 25
    seed(engine, client, auth, rows)
    f = forecast(client, auth)
    assert f["history_level"] == "personal"
    assert f["spent_to_date"] == "2000000.00"
    assert f["expected_recurring_remaining"] == "59000.00"
    # 20 days of 100,000 so far + 59,000 due on the 25th + 10 more days of 100,000
    assert f["predicted_total"] == "3059000.00"
    assert f["predicted_remaining"] == "1059000.00"
    curve = {c["date"]: c["p50"] for c in f["daily_curve"]}
    assert curve["2026-11-24"] == "2400000.00" and curve["2026-11-25"] == "2559000.00"
    assert curve["2026-11-30"] == "3059000.00"


def test_fr_07_01_a_paid_recurring_bill_does_not_inflate_the_daily_average(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = daily("toko", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "100000", "groceries")
    rows += monthly("kos melati", ["3000000"] * 6, day=1, last_month=11, category="housing")
    seed(engine, client, auth, rows)
    f = forecast(client, auth)
    assert f["spent_to_date"] == "5000000.00"  # 20 x 100,000 groceries + the rent paid on Nov 1
    assert f["expected_recurring_remaining"] == "0.00"  # next rent is Dec 1, after the period
    assert f["predicted_remaining"] == "1000000.00"  # not 1,000,000 + a rent spike
    assert f["predicted_total"] == "6000000.00"


def test_fr_07_01_a_rejected_series_goes_back_into_the_daily_average(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = daily("toko", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "100000", "groceries")
    rows += monthly("spotify", ["59000"] * 5, day=25, last_month=10)
    seed(engine, client, auth, rows)
    forecast(client, auth)
    series = by_key(recurring(client, auth), "spotify")
    assert patch(client, auth, series["id"], {"status": "user_rejected"}).status_code == 200
    with engine.begin() as conn:  # the cache is stale because the series changed (FR-07.07)
        conn.execute(text("UPDATE forecasts SET as_of = as_of - interval '7 hours'"))
    f = forecast(client, auth)
    assert f["expected_recurring_remaining"] == "0.00"


def test_fr_07_04_expected_recurring_income_raises_the_period_end_balance(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = daily("toko", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "100000", "groceries")
    rows += monthly("gaji pt maju", ["8000000"] * 5, day=25, last_month=10, category="salary",
                    kind="income")  # fmt: skip
    seed(engine, client, auth, rows)
    f = forecast(client, auth)
    with Session(engine) as s:
        user = s.get(User, uid_of(client, auth))
        assert user is not None
        balance = ForecastService(s, user, NOW).analytics.current_balance()
    # balance now - predicted remaining (10 x 100,000) + the salary due on Nov 25
    assert f["estimated_period_end_balance"] == f"{balance - 1000000 + 8000000:.2f}"


def test_fr_07_01_a_category_forecast_only_adds_its_own_recurring_charges(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = daily("bioskop", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "20000", "entertainment")
    rows += daily("toko", dt.date(2026, 9, 1), dt.date(2026, 11, 20), "100000", "groceries")
    rows += monthly("spotify", ["59000"] * 5, day=25, last_month=10)
    seed(engine, client, auth, rows)
    assert (
        forecast(client, auth, category="entertainment")["expected_recurring_remaining"]
        == "59000.00"
    )
    assert forecast(client, auth, category="groceries")["expected_recurring_remaining"] == "0.00"
