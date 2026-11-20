"""FR-02 transactions API against real PostgreSQL (PRD 7.2, 13.1.4, 13.1.5, 13.2)."""

from __future__ import annotations

import datetime as dt
import io
import threading
import uuid
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup

pytestmark = pytest.mark.integration

JKT = ZoneInfo("Asia/Jakarta")


def now_local() -> dt.datetime:
    return dt.datetime.now(JKT).replace(microsecond=0)


def post_tx(
    client: TestClient, headers: dict[str, str], key: str | None = None, **over: Any
) -> Any:
    body: dict[str, Any] = {
        "transaction_type": "expense",
        "amount": "25000",
        "description": "Kopi Kenangan Senopati",
        "transaction_date": (now_local() - dt.timedelta(hours=1)).isoformat(),
    }
    body.update(over)
    return client.post(
        f"{API}/transactions",
        json=body,
        headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex},
    )


def make(client: TestClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    r = post_tx(client, headers, **over)
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


# --- create ------------------------------------------------------------------------------------
def test_fr_02_01_create_minimal_transaction(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    body = make(client, auth, amount=25000.5, description="  Kopi Kenangan\x00 Senopati  ")
    assert body["amount"] == "25000.50" and body["description"] == "Kopi Kenangan  Senopati"
    assert body["version"] == 1 and body["source"] == "manual" and body["has_time"] is True
    assert body["transaction_date"].endswith("+07:00")
    assert body["merchant"] and body["merchant_key"]  # derived (7.3.2)
    # No ML yet (T-18): saving works and the row is flagged for review.
    assert body["category"]["slug"] == "uncategorized"
    assert body["category_status"] == "needs_review"
    assert body["categorization"]["decision"] == "needs_review"
    assert body["categorization"]["source"] == "fallback"
    assert body["warnings"] == [] and "user_id" not in body
    with engine.connect() as conn:
        events = conn.execute(
            text("SELECT event_type, payload FROM outbox_events WHERE aggregate_id = :i"),
            {"i": body["id"]},
        ).all()
    assert [e[0] for e in events] == ["transaction.created"]
    payload = events[0][1]
    assert payload["data"]["transaction_id"] == body["id"] and payload["schema_version"] == 1
    assert "Kopi" not in str(payload) and "25000" not in str(payload)  # ids and enums only


def test_fr_02_01_money_is_exact_decimal(client: TestClient, auth: dict[str, str]) -> None:
    assert make(client, auth, amount="0.01")["amount"] == "0.01"
    assert make(client, auth, amount="9999999.99")["amount"] == "9999999.99"
    assert make(client, auth, amount=1500000)["amount"] == "1500000.00"


@pytest.mark.parametrize(
    ("over", "field", "code"),
    [
        ({"amount": 0}, "amount", "INVALID_AMOUNT"),
        ({"amount": "-5"}, "amount", "INVALID_AMOUNT"),
        ({"amount": "abc"}, "amount", "INVALID_AMOUNT"),
        ({"amount": "1.234"}, "amount", "INVALID_AMOUNT"),
        ({"amount": True}, "amount", "INVALID_AMOUNT"),
        ({"amount": "NaN"}, "amount", "INVALID_AMOUNT"),
        ({"amount": "1e999999"}, "amount", "INVALID_AMOUNT"),
        ({"amount": "1000000000.01"}, "amount", "AMOUNT_OUT_OF_RANGE"),
        ({"description": "   "}, "description", "MISSING_FIELD"),
        ({"description": "x" * 201}, "description", "FIELD_TOO_LONG"),
        ({"merchant": "m" * 101}, "merchant", "FIELD_TOO_LONG"),
        ({"notes": "n" * 501}, "notes", "FIELD_TOO_LONG"),
        ({"transaction_date": "01/11/2026"}, "transaction_date", "INVALID_DATE"),
        ({"transaction_date": "1999-12-31"}, "transaction_date", "INVALID_DATE"),
        ({"transaction_date": "2999-01-01"}, "transaction_date", "FUTURE_DATE"),
        ({"payment_method": "bitcoin"}, "payment_method", "INVALID_PAYMENT_METHOD"),
        ({"category": "nope"}, "category", "UNKNOWN_CATEGORY"),
        ({"category": "salary"}, "category", "CATEGORY_TYPE_MISMATCH"),
    ],
)
def test_fr_02_validation_codes(
    client: TestClient, auth: dict[str, str], over: dict[str, Any], field: str, code: str
) -> None:
    r = post_tx(client, auth, **over)
    assert r.status_code == 422, r.text
    err = r.json()["errors"][0]
    assert (err["field"], err["code"]) == (field, code)


def test_fr_02_unknown_and_server_fields_are_rejected(
    client: TestClient, auth: dict[str, str]
) -> None:
    for extra in (
        {"user_id": str(uuid.uuid4())},
        {"category_status": "user_set"},
        {"source": "csv"},
    ):
        assert post_tx(client, auth, **extra).status_code == 422
    assert post_tx(client, auth, transaction_type="refund").status_code == 422


def test_fr_02_missing_required_fields(client: TestClient, auth: dict[str, str]) -> None:
    r = client.post(f"{API}/transactions", json={}, headers={**auth, "Idempotency-Key": "k" * 12})
    assert r.status_code == 422
    assert {e["code"] for e in r.json()["errors"]} == {"FIELD_REQUIRED"}


def test_fr_02_dates_are_interpreted_in_user_timezone(
    client: TestClient, auth: dict[str, str]
) -> None:
    yesterday = (now_local() - dt.timedelta(days=1)).date()
    date_only = make(client, auth, transaction_date=yesterday.isoformat())
    assert date_only["has_time"] is False
    assert date_only["transaction_date"] == f"{yesterday.isoformat()}T00:00:00+07:00"
    naive = make(client, auth, transaction_date=f"{yesterday.isoformat()}T13:30:00")
    assert naive["transaction_date"] == f"{yesterday.isoformat()}T13:30:00+07:00"
    utc = make(client, auth, transaction_date=f"{yesterday.isoformat()}T03:00:00Z")
    assert utc["transaction_date"] == f"{yesterday.isoformat()}T10:00:00+07:00"
    tomorrow = (now_local() + dt.timedelta(days=1)).date().isoformat()
    assert post_tx(client, auth, transaction_date=tomorrow).status_code == 201  # <= 1 day ahead


def test_fr_02_payment_method_aliases_and_category_slug(
    client: TestClient, auth: dict[str, str]
) -> None:
    body = make(client, auth, payment_method="E-Wallet", category="groceries")
    assert body["payment_method"] == "e_wallet"
    assert body["category"]["slug"] == "groceries" and body["category_status"] == "user_set"
    assert make(client, auth, payment_method="bank")["payment_method"] == "bank_transfer"
    assert make(client, auth, payment_method="QR")["payment_method"] == "qris"


def test_17_2_long_numbers_are_masked_before_storage(
    client: TestClient, auth: dict[str, str]
) -> None:
    body = make(
        client,
        auth,
        description="Bayar kartu 4111 1111 1111 1111 di toko",
        notes="rek 1234567890123456789 ok",
    )
    assert "4111" not in body["description"] and "****1111" in body["description"]
    assert "****6789" in body["notes"]
    assert make(client, auth, description="order 12345678 selesai")["description"].endswith(
        "selesai"
    )


def test_fr_02_logs_never_contain_transaction_text_or_amounts(
    client: TestClient, auth: dict[str, str], log_stream: io.StringIO
) -> None:
    make(
        client,
        auth,
        description="SENTINEL-desc-xyz",
        merchant="SENTINEL-merchant-xyz",
        notes="SENTINEL-notes-xyz",
        amount="73519.37",
    )
    client.get(f"{API}/transactions?q=SENTINEL-desc-xyz", headers=auth)
    logs = log_stream.getvalue()
    assert logs
    for secret in ("SENTINEL-desc", "SENTINEL-merchant", "SENTINEL-notes", "73519"):
        assert secret not in logs, secret


# --- idempotency -------------------------------------------------------------------------------
def test_13_1_5_idempotency_key_is_required_and_validated(
    client: TestClient, auth: dict[str, str]
) -> None:
    body = {
        "transaction_type": "expense",
        "amount": "1",
        "description": "x",
        "transaction_date": "2026-01-02",
    }
    r = client.post(f"{API}/transactions", json=body, headers=auth)
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    r = client.post(f"{API}/transactions", json=body, headers={**auth, "Idempotency-Key": "short"})
    assert r.status_code == 400
    r = client.post(
        f"{API}/transactions/bulk-delete", json={"ids": [str(uuid.uuid4())]}, headers=auth
    )
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_13_1_5_same_key_same_body_replays_without_a_second_row(
    client: TestClient, auth: dict[str, str]
) -> None:
    key = uuid.uuid4().hex
    first = post_tx(client, auth, key=key, transaction_date="2026-03-05")
    second = post_tx(client, auth, key=key, transaction_date="2026-03-05")
    assert first.status_code == second.status_code == 201
    assert (
        second.headers["Idempotent-Replayed"] == "true"
        and "Idempotent-Replayed" not in first.headers
    )
    assert first.json() == second.json()
    count = client.get(f"{API}/transactions/count", headers=auth).json()["count"]
    assert count == 1


def test_13_1_5_same_key_different_body_is_409(client: TestClient, auth: dict[str, str]) -> None:
    key = uuid.uuid4().hex
    assert post_tx(client, auth, key=key, amount="100").status_code == 201
    r = post_tx(client, auth, key=key, amount="200")
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert client.get(f"{API}/transactions/count", headers=auth).json()["count"] == 1


def test_13_1_5_keys_are_per_user(client: TestClient, auth: dict[str, str]) -> None:
    other = signup(client)
    key = uuid.uuid4().hex
    a = post_tx(client, auth, key=key)
    b = post_tx(client, other, key=key)
    assert a.status_code == b.status_code == 201 and a.json()["id"] != b.json()["id"]


def test_13_1_5_failed_request_does_not_consume_the_key(
    client: TestClient, auth: dict[str, str]
) -> None:
    key = uuid.uuid4().hex
    assert post_tx(client, auth, key=key, amount="0").status_code == 422
    assert (
        post_tx(client, auth, key=key, amount="0").status_code == 422
    )  # still validated, not replayed
    assert post_tx(client, auth, key=key, amount="50").status_code == 201


def test_13_1_5_expired_key_can_be_reused(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    key = uuid.uuid4().hex
    first = post_tx(client, auth, key=key, amount="100")
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE idempotency_keys SET created_at = now() - interval '25 hours' WHERE key = :k"
            ),
            {"k": key},
        )
    second = post_tx(client, auth, key=key, amount="200")
    assert second.status_code == 201 and second.json()["id"] != first.json()["id"]


def test_13_1_5_concurrent_requests_with_one_key_create_one_row(
    client: TestClient, auth: dict[str, str]
) -> None:
    key = uuid.uuid4().hex
    results: list[Any] = []

    def go() -> None:
        results.append(post_tx(client, auth, key=key, transaction_date="2026-04-01"))

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in results) == [201] * 4
    assert len({r.json()["id"] for r in results}) == 1
    assert client.get(f"{API}/transactions/count", headers=auth).json()["count"] == 1


# --- duplicates --------------------------------------------------------------------------------
def test_fr_02_12_duplicate_within_10_minutes_is_saved_and_flagged(
    client: TestClient, auth: dict[str, str]
) -> None:
    base = now_local() - dt.timedelta(hours=3)
    first = make(client, auth, transaction_date=base.isoformat())
    second = make(client, auth, transaction_date=(base + dt.timedelta(minutes=9)).isoformat())
    assert second["warnings"] == ["POSSIBLE_DUPLICATE"]
    assert second["possible_duplicate_of"] == first["id"] and first["possible_duplicate_of"] is None
    far = make(client, auth, transaction_date=(base + dt.timedelta(minutes=25)).isoformat())
    assert far["warnings"] == []


@pytest.mark.parametrize(
    "over",
    [
        {"amount": "25001"},
        {"transaction_type": "income", "category": None},
        {"merchant": "Warteg Bahari"},
    ],
)
def test_fr_02_12_any_differing_key_field_is_not_a_duplicate(
    client: TestClient, auth: dict[str, str], over: dict[str, Any]
) -> None:
    when = (now_local() - dt.timedelta(hours=2)).isoformat()
    make(client, auth, transaction_date=when, merchant="Kopi Kenangan")
    over = {k: v for k, v in over.items() if v is not None}
    assert (
        make(client, auth, transaction_date=when, **{"merchant": "Kopi Kenangan", **over})[
            "warnings"
        ]
        == []
    )


def test_fr_02_12_date_only_rows_compare_by_local_day(
    client: TestClient, auth: dict[str, str]
) -> None:
    day = (now_local() - dt.timedelta(days=2)).date().isoformat()
    first = make(client, auth, transaction_date=day)
    assert make(client, auth, transaction_date=day)["possible_duplicate_of"] == first["id"]
    timed = make(
        client, auth, transaction_date=f"{day}T20:15:00"
    )  # same local day as a date-only row
    assert timed["possible_duplicate_of"] == first["id"]


def test_fr_02_12_other_users_transactions_never_count(
    client: TestClient, auth: dict[str, str]
) -> None:
    other = signup(client)
    when = (now_local() - dt.timedelta(hours=2)).isoformat()
    make(client, other, transaction_date=when)
    assert make(client, auth, transaction_date=when)["warnings"] == []


def test_fr_02_15_dismissing_a_duplicate_clears_flag_and_keeps_it_cleared(
    client: TestClient, auth: dict[str, str]
) -> None:
    when = (now_local() - dt.timedelta(hours=2)).isoformat()
    make(client, auth, transaction_date=when)
    dup = make(client, auth, transaction_date=when)
    r = client.post(f"{API}/transactions/{dup['id']}/dismiss-duplicate", headers=auth)
    assert r.status_code == 200
    assert r.json()["possible_duplicate_of"] is None and r.json()["duplicate_dismissed"] is True
    # Editing a key field must not re-flag a dismissed transaction.
    patched = client.patch(
        f"{API}/transactions/{dup['id']}", json={"notes": "ok", "amount": "25000.00"}, headers=auth
    )
    assert patched.json()["possible_duplicate_of"] is None
    assert (
        client.get(f"{API}/transactions?possible_duplicate=true", headers=auth).json()["items"]
        == []
    )


def test_fr_02_12_editing_into_and_out_of_a_duplicate_reflags(
    client: TestClient, auth: dict[str, str]
) -> None:
    when = (now_local() - dt.timedelta(hours=2)).isoformat()
    first = make(client, auth, transaction_date=when)
    other = make(client, auth, transaction_date=when, amount="999")
    assert other["possible_duplicate_of"] is None
    into = client.patch(f"{API}/transactions/{other['id']}", json={"amount": "25000"}, headers=auth)
    assert into.json()["possible_duplicate_of"] == first["id"]
    out = client.patch(f"{API}/transactions/{other['id']}", json={"amount": "777"}, headers=auth)
    assert out.json()["possible_duplicate_of"] is None


# --- list, filters, pagination -------------------------------------------------------------------
@pytest.fixture
def seeded(client: TestClient, auth: dict[str, str]) -> list[dict[str, Any]]:
    """Seven transactions on distinct local days, oldest first."""
    spec = [
        ("expense", "10000", "Kopi Kenangan", "food_beverage", "e_wallet"),
        ("expense", "250000", "Indomaret Fresh", "groceries", "debit_card"),
        ("expense", "18000", "Grab Bike", "transportation", "e_wallet"),
        ("income", "5000000", "Gaji Bulanan", "salary", "bank_transfer"),
        ("expense", "99999", "Diskon 50% off_sale", "shopping", "qris"),
        ("expense", "65000", "Netflix", "entertainment", "credit_card"),
        ("transfer", "100000", "Top up OVO", "transfer", "e_wallet"),
    ]
    out = []
    for i, (typ, amount, desc, cat, pay) in enumerate(spec):
        day = (now_local() - dt.timedelta(days=len(spec) - i)).date().isoformat()
        out.append(
            make(
                client,
                auth,
                transaction_type=typ,
                amount=amount,
                description=desc,
                category=cat,
                payment_method=pay,
                transaction_date=f"{day}T12:00:00",
            )
        )
    return out


def ids(resp: Any) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [i["id"] for i in resp.json()["items"]]


def test_fr_02_02_default_order_is_newest_first(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    got = ids(client.get(f"{API}/transactions", headers=auth))
    assert got == [t["id"] for t in reversed(seeded)]
    assert client.get(f"{API}/transactions", headers=auth).json()["next_cursor"] is None


def test_13_1_4_cursor_pagination_walks_every_row_once(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        url = f"{API}/transactions?limit=3" + (f"&cursor={cursor}" if cursor else "")
        r = client.get(url, headers=auth)
        assert r.status_code == 200
        seen += [i["id"] for i in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        pages += 1
        if cursor is None:
            break
    assert pages == 3 and seen == [t["id"] for t in reversed(seeded)]


def test_13_1_4_pagination_is_stable_with_equal_sort_keys(
    client: TestClient, auth: dict[str, str]
) -> None:
    for _ in range(5):  # identical date and amount, so only the id tiebreaker orders them
        make(
            client, auth, transaction_date="2026-02-02", amount="500", description=uuid.uuid4().hex
        )
    for sort in ("date", "amount"):
        seen: list[str] = []
        cursor = None
        while True:
            url = f"{API}/transactions?limit=2&sort={sort}" + (
                f"&cursor={cursor}" if cursor else ""
            )
            body = client.get(url, headers=auth).json()
            seen += [i["id"] for i in body["items"]]
            cursor = body["next_cursor"]
            if not cursor:
                break
        assert len(seen) == len(set(seen)) == 5


def test_fr_02_02_sort_by_amount_desc(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    r = client.get(f"{API}/transactions?sort=amount", headers=auth)
    amounts = [float(i["amount"]) for i in r.json()["items"]]
    assert amounts == sorted(amounts, reverse=True) and amounts[0] == 5000000.0


def test_13_1_4_cursor_must_be_untampered_and_belong_to_the_caller(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    cursor = client.get(f"{API}/transactions?limit=2", headers=auth).json()["next_cursor"]
    for bad in (cursor + "x", "garbage", cursor.split(".")[0], "." + cursor.split(".")[1], ""):
        r = client.get(f"{API}/transactions", params={"cursor": bad}, headers=auth)
        assert r.status_code in (400, 200)
        if bad:
            assert r.status_code == 400 and r.json()["code"] == "INVALID_CURSOR", bad
    other = signup(client)
    r = client.get(f"{API}/transactions", params={"cursor": cursor}, headers=other)
    assert r.status_code == 400 and r.json()["code"] == "INVALID_CURSOR"
    r = client.get(f"{API}/transactions", params={"sort": "amount", "cursor": cursor}, headers=auth)
    assert r.status_code == 400


def test_fr_02_02_limit_bounds(client: TestClient, auth: dict[str, str]) -> None:
    assert client.get(f"{API}/transactions?limit=200", headers=auth).status_code == 200
    for bad in ("0", "201", "-1", "abc"):
        assert client.get(f"{API}/transactions?limit={bad}", headers=auth).status_code == 422


def test_fr_02_02_filters(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    def q(qs: str) -> list[str]:
        return [
            seeded.index(next(s for s in seeded if s["id"] == i))
            for i in ids(client.get(f"{API}/transactions?{qs}", headers=auth))
        ]

    day = lambda n: (now_local() - dt.timedelta(days=n)).date().isoformat()  # noqa: E731
    assert sorted(q("transaction_type=income")) == [3]
    assert sorted(q("category=groceries&category=salary")) == [1, 3]
    assert sorted(q("payment_method=e-wallet")) == [0, 2, 6]
    assert sorted(q("payment_method=e_wallet&payment_method=qris")) == [0, 2, 4, 6]
    assert sorted(q("min_amount=100000&max_amount=250000")) == [1, 6]
    assert sorted(q("category_status=user_set")) == list(range(7))
    assert q("category_status=needs_review") == []
    assert sorted(q(f"date_from={day(5)}&date_to={day(3)}")) == [2, 3, 4]  # inclusive both ends
    assert sorted(q(f"date_from={day(1)}")) == [6]
    assert sorted(q("q=KOPI")) == [0]
    assert sorted(q("q=oVo")) == [6]
    assert sorted(q("q=%25")) == [4]  # literal "%" only, not a wildcard
    assert sorted(q("q=_")) == [4]  # literal "_" only
    assert q("q=%25%25%25") == []
    for bad in (
        "category=nope",
        "payment_method=bitcoin",
        "category_status=weird",
        "min_amount=abc",
        "date_from=31-12-2026",
    ):
        assert client.get(f"{API}/transactions?{bad}", headers=auth).status_code == 422, bad


def test_fr_02_02_count_uses_the_same_filters(
    client: TestClient, auth: dict[str, str], seeded: list[dict[str, Any]]
) -> None:
    for qs, expected in (("", 7), ("transaction_type=expense", 5), ("q=kopi", 1), ("limit=2", 7)):
        r = client.get(f"{API}/transactions/count?{qs}", headers=auth)
        assert r.json() == {"count": expected}, qs


def test_fr_02_02_date_filters_use_the_users_timezone(
    client: TestClient, auth: dict[str, str]
) -> None:
    # 01:00 local on the 10th is still the 9th in UTC; the local-day filter must include it.
    make(client, auth, transaction_date="2026-03-10T01:00:00")
    assert (
        client.get(
            f"{API}/transactions/count?date_from=2026-03-10&date_to=2026-03-10", headers=auth
        ).json()["count"]
        == 1
    )
    assert (
        client.get(
            f"{API}/transactions/count?date_from=2026-03-09&date_to=2026-03-09", headers=auth
        ).json()["count"]
        == 0
    )


# --- read / update / delete ----------------------------------------------------------------------
def test_fr_02_01_get_by_id_and_unknown_id(client: TestClient, auth: dict[str, str]) -> None:
    tx = make(client, auth)
    r = client.get(f"{API}/transactions/{tx['id']}", headers=auth)
    assert r.status_code == 200 and r.json()["id"] == tx["id"] and "categorization" not in r.json()
    assert client.get(f"{API}/transactions/{uuid.uuid4()}", headers=auth).status_code == 404
    assert client.get(f"{API}/transactions/not-a-uuid", headers=auth).status_code == 422


def test_fr_02_03_patch_updates_fields_and_bumps_version(
    client: TestClient, auth: dict[str, str]
) -> None:
    tx = make(client, auth, notes="old")
    r = client.patch(
        f"{API}/transactions/{tx['id']}",
        json={
            "amount": "30000",
            "description": "Kopi baru",
            "payment_method": "qris",
            "notes": None,
            "category": "food_beverage",
            "merchant": "Janji Jiwa",
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["amount"] == "30000.00" and body["description"] == "Kopi baru"
    assert body["notes"] is None and body["payment_method"] == "qris"
    assert body["merchant"] == "Janji Jiwa" and body["merchant_key"] == "janji jiwa"
    assert body["category"]["slug"] == "food_beverage" and body["category_status"] == "user_set"
    assert body["version"] == 2 and body["updated_at"] >= tx["updated_at"]
    assert client.get(f"{API}/transactions/{tx['id']}", headers=auth).json()["version"] == 2


def test_fr_02_03_patch_validates_like_create(client: TestClient, auth: dict[str, str]) -> None:
    tx = make(client, auth)
    for body, code in (
        ({"amount": "0"}, "INVALID_AMOUNT"),
        ({"amount": None}, "INVALID_AMOUNT"),
        ({"description": " "}, "MISSING_FIELD"),
        ({"transaction_date": "2999-01-01"}, "FUTURE_DATE"),
        ({"category": "salary"}, "CATEGORY_TYPE_MISMATCH"),
        ({"category": "nope"}, "UNKNOWN_CATEGORY"),
    ):
        r = client.patch(f"{API}/transactions/{tx['id']}", json=body, headers=auth)
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == code, body
    assert (
        client.patch(
            f"{API}/transactions/{tx['id']}", json={"user_id": "x"}, headers=auth
        ).status_code
        == 422
    )
    assert client.get(f"{API}/transactions/{tx['id']}", headers=auth).json()["version"] == 1


def test_fr_02_03_if_match_guards_against_lost_updates(
    client: TestClient, auth: dict[str, str]
) -> None:
    tx = make(client, auth)
    url = f"{API}/transactions/{tx['id']}"
    ok = client.patch(url, json={"notes": "a"}, headers={**auth, "If-Match": '"1"'})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = client.patch(url, json={"notes": "b"}, headers={**auth, "If-Match": '"1"'})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    assert (
        client.patch(url, json={"notes": "c"}, headers={**auth, "If-Match": "abc"}).status_code
        == 400
    )
    assert (
        client.patch(url, json={"notes": "d"}, headers={**auth, "If-Match": 'W/"2"'}).status_code
        == 200
    )
    assert client.get(url, headers=auth).json()["notes"] == "d"


def test_fr_02_03_changing_type_under_an_incompatible_category_resets_it(
    client: TestClient, auth: dict[str, str]
) -> None:
    tx = make(client, auth, category="groceries")
    r = client.patch(
        f"{API}/transactions/{tx['id']}", json={"transaction_type": "income"}, headers=auth
    )
    assert r.json()["category"]["slug"] == "uncategorized"
    assert r.json()["category_status"] == "needs_review"
    ok = client.patch(
        f"{API}/transactions/{tx['id']}",
        json={"transaction_type": "expense", "category": "shopping"},
        headers=auth,
    )
    assert ok.json()["category"]["slug"] == "shopping"


def test_fr_02_03_events_only_for_rescoring_changes(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    tx = make(client, auth)

    def events() -> list[str]:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT event_type FROM outbox_events WHERE aggregate_id = :i ORDER BY id"),
                {"i": tx["id"]},
            )
            return [r[0] for r in rows]

    url = f"{API}/transactions/{tx['id']}"
    client.patch(
        url,
        json={"notes": "n", "description": "other text", "payment_method": "cash"},
        headers=auth,
    )
    assert events() == ["transaction.created"]
    client.patch(url, json={"amount": "26000"}, headers=auth)
    assert events() == ["transaction.created", "transaction.updated"]
    client.patch(url, json={"amount": "26000"}, headers=auth)  # same value: nothing changed
    assert events() == ["transaction.created", "transaction.updated"]
    client.delete(url, headers=auth)
    assert events() == ["transaction.created", "transaction.updated", "transaction.deleted"]


def test_fr_02_04_delete_is_hard_and_second_delete_is_404(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    tx = make(client, auth)
    assert client.delete(f"{API}/transactions/{tx['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/transactions/{tx['id']}", headers=auth).status_code == 404
    assert client.delete(f"{API}/transactions/{tx['id']}", headers=auth).status_code == 404
    with engine.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM transactions WHERE id = :i"), {"i": tx["id"]}
            ).scalar_one()
            == 0
        )


def test_fr_02_04_deleting_the_original_unflags_its_duplicate(
    client: TestClient, auth: dict[str, str]
) -> None:
    when = (now_local() - dt.timedelta(hours=2)).isoformat()
    first = make(client, auth, transaction_date=when)
    dup = make(client, auth, transaction_date=when)
    client.delete(f"{API}/transactions/{first['id']}", headers=auth)
    assert (
        client.get(f"{API}/transactions/{dup['id']}", headers=auth).json()["possible_duplicate_of"]
        is None
    )


# --- bulk ---------------------------------------------------------------------------------------
def bulk(
    client: TestClient,
    auth: dict[str, str],
    path: str,
    body: dict[str, Any],
    key: str | None = None,
) -> Any:
    return client.post(
        f"{API}/transactions/{path}",
        json=body,
        headers={**auth, "Idempotency-Key": key or uuid.uuid4().hex},
    )


def test_fr_02_05_bulk_delete_is_atomic(client: TestClient, auth: dict[str, str]) -> None:
    mine = [
        make(client, auth, amount=str(i + 1), transaction_date="2026-05-01")["id"] for i in range(3)
    ]
    r = bulk(client, auth, "bulk-delete", {"ids": [*mine, str(uuid.uuid4())]})
    assert r.status_code == 404
    assert (
        client.get(f"{API}/transactions/count", headers=auth).json()["count"] == 3
    )  # nothing deleted
    ok = bulk(client, auth, "bulk-delete", {"ids": [*mine, mine[0]]})  # duplicate id tolerated
    assert ok.status_code == 200 and ok.json() == {"deleted": 3}
    assert client.get(f"{API}/transactions/count", headers=auth).json()["count"] == 0


def test_fr_02_05_bulk_limits_and_shape(client: TestClient, auth: dict[str, str]) -> None:
    too_many = [str(uuid.uuid4()) for _ in range(201)]
    assert bulk(client, auth, "bulk-delete", {"ids": too_many}).status_code == 422
    assert bulk(client, auth, "bulk-delete", {"ids": []}).status_code == 422
    assert bulk(client, auth, "bulk-delete", {"ids": ["x"]}).status_code == 422
    assert (
        bulk(
            client, auth, "bulk-categorize", {"ids": too_many, "category": "groceries"}
        ).status_code
        == 422
    )


def test_fr_02_05_bulk_categorize_sets_user_set_and_checks_types(
    client: TestClient, auth: dict[str, str]
) -> None:
    a = make(client, auth, amount="1", transaction_date="2026-05-01")
    b = make(client, auth, amount="2", transaction_date="2026-05-01")
    inc = make(client, auth, amount="3", transaction_type="income", transaction_date="2026-05-01")
    r = bulk(client, auth, "bulk-categorize", {"ids": [a["id"], b["id"]], "category": "groceries"})
    assert r.status_code == 200 and r.json() == {"updated": 2}
    for tx in (a, b):
        got = client.get(f"{API}/transactions/{tx['id']}", headers=auth).json()
        assert got["category"]["slug"] == "groceries" and got["category_status"] == "user_set"
        assert got["version"] == 2
    mismatch = bulk(
        client, auth, "bulk-categorize", {"ids": [a["id"], inc["id"]], "category": "groceries"}
    )
    assert (
        mismatch.status_code == 422
        and mismatch.json()["errors"][0]["code"] == "CATEGORY_TYPE_MISMATCH"
    )
    assert (
        client.get(f"{API}/transactions/{a['id']}", headers=auth).json()["version"] == 2
    )  # untouched


def test_13_1_5_bulk_requests_replay_by_key(client: TestClient, auth: dict[str, str]) -> None:
    tx = make(client, auth)
    key = uuid.uuid4().hex
    first = bulk(client, auth, "bulk-delete", {"ids": [tx["id"]]}, key)
    again = bulk(
        client, auth, "bulk-delete", {"ids": [tx["id"]]}, key
    )  # would be 404 without replay
    assert first.status_code == again.status_code == 200 and again.json() == {"deleted": 1}


# --- ownership (the full BOLA suite is T-16) ----------------------------------------------------
def test_fr_02_01_other_users_transactions_are_404_everywhere(
    client: TestClient, auth: dict[str, str]
) -> None:
    mine = make(client, auth)
    other = signup(client)
    url = f"{API}/transactions/{mine['id']}"
    assert client.get(url, headers=other).status_code == 404
    assert client.patch(url, json={"notes": "x"}, headers=other).status_code == 404
    assert client.delete(url, headers=other).status_code == 404
    assert client.post(f"{url}/dismiss-duplicate", headers=other).status_code == 404
    assert bulk(client, other, "bulk-delete", {"ids": [mine["id"]]}).status_code == 404
    assert (
        bulk(
            client, other, "bulk-categorize", {"ids": [mine["id"]], "category": "groceries"}
        ).status_code
        == 404
    )
    assert client.get(f"{API}/transactions", headers=other).json()["items"] == []
    assert client.get(f"{API}/transactions/count", headers=other).json()["count"] == 0
    missing = client.get(f"{API}/transactions/{uuid.uuid4()}", headers=other)
    foreign = client.get(url, headers=other)
    assert missing.json()["code"] == foreign.json()["code"] == "NOT_FOUND"
    assert client.get(url, headers=auth).status_code == 200  # untouched


def test_13_1_1_transaction_endpoints_require_authentication(client: TestClient) -> None:
    for method, path in (
        ("GET", "/transactions"),
        ("GET", "/transactions/count"),
        ("POST", "/transactions"),
        ("GET", f"/transactions/{uuid.uuid4()}"),
        ("PATCH", f"/transactions/{uuid.uuid4()}"),
        ("DELETE", f"/transactions/{uuid.uuid4()}"),
        ("POST", "/transactions/bulk-delete"),
        ("GET", "/categories"),
    ):
        assert client.request(method, f"{API}{path}", json={}).status_code == 401, (method, path)


def test_fr_02_user_cascade_removes_transactions_and_idempotency_keys(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    make(client, auth)
    r = client.request(
        "DELETE",
        f"{API}/users/me",
        headers=auth,
        json={"password": "correct horse battery", "confirm": "DELETE"},
    )
    assert r.status_code == 204
    with engine.connect() as conn:
        # the deleted user's rows are gone; counts for other tests' users are unaffected
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM idempotency_keys WHERE user_id NOT IN (SELECT id FROM users)"
                )
            ).scalar_one()
            == 0
        )


# --- categories ---------------------------------------------------------------------------------
def test_13_2_categories_list_with_etag(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get(f"{API}/categories", headers=auth)
    assert r.status_code == 200 and len(r.json()) == 20
    assert {"id", "slug", "name", "transaction_type"} == set(r.json()[0])
    assert next(c for c in r.json() if c["slug"] == "uncategorized")["transaction_type"] == "any"
    etag = r.headers["ETag"]
    again = client.get(f"{API}/categories", headers={**auth, "If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
