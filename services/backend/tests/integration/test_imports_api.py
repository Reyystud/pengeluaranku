"""FR-02.06 .. FR-02.14 CSV import against real PostgreSQL (PRD 7.2.3, 13.2)."""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.integration.conftest import API, signup
from tests.integration.test_transactions_api import make

pytestmark = pytest.mark.integration

HEADER = "date,description,amount,type,payment_method,merchant,category,notes\n"
YESTERDAY = (dt.date.today() - dt.timedelta(days=2)).isoformat()


def csv_bytes(*rows: str, header: str = HEADER) -> bytes:
    return (header + "".join(r + "\n" for r in rows)).encode()


def upload(client: TestClient, auth: dict[str, str], content: bytes, name: str = "t.csv") -> Any:
    return client.post(
        f"{API}/transactions/imports", files={"file": (name, content, "text/csv")}, headers=auth
    )


def preview(client: TestClient, auth: dict[str, str], *rows: str, **kw: Any) -> dict[str, Any]:
    r = upload(client, auth, csv_bytes(*rows, **kw))
    assert r.status_code == 201, r.text
    return r.json()  # type: ignore[no-any-return]


def commit(
    client: TestClient, auth: dict[str, str], import_id: str, key: str | None = None, **body: Any
) -> Any:
    return client.post(
        f"{API}/transactions/imports/{import_id}/commit",
        json=body,
        headers={**auth, "Idempotency-Key": key or uuid.uuid4().hex},
    )


def count_tx(engine: Engine, user_email_like: str = "%") -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM transactions")).scalar_one())


def tx_for_import(engine: Engine, import_id: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT description, amount, category_status, source, has_time, "
                    "possible_duplicate_of, import_id FROM transactions "
                    "WHERE import_id = :i ORDER BY description"
                ),
                {"i": import_id},
            )
        )


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    return signup(client)


GOOD = [
    f"{YESTERDAY},Kopi Kenangan,25000,expense,e-wallet,,,",
    f"{YESTERDAY} 18:30,Gaji,Rp 1.500.000,in,bank,,,Bulan ini",
    "bad-date,Makan,10000,expense,,,,",
]


# --- preview -----------------------------------------------------------------------------------
def test_fr_02_06_preview_stages_without_writing_transactions(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    before = count_tx(engine)
    p = preview(client, auth, *GOOD)
    assert count_tx(engine) == before  # nothing written to transactions
    assert p["status"] == "previewed" and p["filename"] == "t.csv"
    assert p["summary"] == {"row_count": 3, "valid": 2, "invalid": 1, "duplicate": 0}
    rows = {r["row_number"]: r for r in p["rows"]}
    assert set(rows) == {2, 3, 4}  # header is row 1
    assert rows[2]["status"] == "valid" and rows[2]["values"]["amount"] == "25000.00"
    assert rows[2]["values"]["has_time"] is False and rows[3]["values"]["has_time"] is True
    assert rows[3]["values"]["amount"] == "1500000.00"  # Rp 1.500.000
    assert rows[3]["values"]["transaction_type"] == "income"
    assert rows[2]["values"]["payment_method"] == "e_wallet"
    assert rows[2]["values"]["transaction_date"].endswith("+07:00")
    assert rows[2]["prediction"]["decision"] == "needs_review"
    err = rows[4]["errors"][0]
    assert err == {
        "row_number": 4,
        "column": "date",
        "code": "INVALID_DATE",
        "message": err["message"],
        "value": "bad-date",
    }
    assert rows[4]["values"] is None
    assert p["warnings"] == []
    exp = dt.datetime.fromisoformat(p["expires_at"].replace("Z", "+00:00"))
    assert dt.timedelta(hours=23) < exp - dt.datetime.now(dt.UTC) <= dt.timedelta(hours=24)


def test_fr_02_06_every_row_error_code(client: TestClient, auth: dict[str, str]) -> None:
    long_desc = "x" * 201
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    p = preview(
        client,
        auth,
        ",x,1,expense,,,,",  # MISSING_FIELD date
        f"{YESTERDAY},,1,expense,,,,",  # MISSING_FIELD description
        f"{YESTERDAY},x,,expense,,,,",  # MISSING_FIELD amount
        f"{YESTERDAY},x,1,,,,,",  # MISSING_FIELD type
        f"{future},x,1,expense,,,,",  # FUTURE_DATE
        "1999-12-31,x,1,expense,,,,",  # INVALID_DATE (before 2000)
        f"{YESTERDAY},x,-5,expense,,,,",  # INVALID_AMOUNT
        f"{YESTERDAY},x,2000000000,expense,,,,",  # AMOUNT_OUT_OF_RANGE
        f"{YESTERDAY},x,1,refund,,,,",  # INVALID_TYPE
        f"{YESTERDAY},x,1,expense,bitcoin,,,",  # INVALID_PAYMENT_METHOD
        f"{YESTERDAY},x,1,expense,,,nonexistent,",  # UNKNOWN_CATEGORY
        f"{YESTERDAY},x,1,expense,,,salary,",  # CATEGORY_TYPE_MISMATCH
        f"{YESTERDAY},{long_desc},1,expense,,,,",  # FIELD_TOO_LONG
        f"{YESTERDAY},x,1,expense,,{'m' * 101},,",  # FIELD_TOO_LONG merchant
    )
    codes = [(r["errors"][0]["column"], r["errors"][0]["code"]) for r in p["rows"]]
    assert codes == [
        ("date", "MISSING_FIELD"),
        ("description", "MISSING_FIELD"),
        ("amount", "MISSING_FIELD"),
        ("type", "MISSING_FIELD"),
        ("date", "FUTURE_DATE"),
        ("date", "INVALID_DATE"),
        ("amount", "INVALID_AMOUNT"),
        ("amount", "AMOUNT_OUT_OF_RANGE"),
        ("type", "INVALID_TYPE"),
        ("payment_method", "INVALID_PAYMENT_METHOD"),
        ("category", "UNKNOWN_CATEGORY"),
        ("category", "CATEGORY_TYPE_MISMATCH"),
        ("description", "FIELD_TOO_LONG"),
        ("merchant", "FIELD_TOO_LONG"),
    ]
    assert p["summary"]["invalid"] == 14
    long_row = next(
        r
        for r in p["rows"]
        if r["errors"][0]["column"] == "description" and r["errors"][0]["code"] == "FIELD_TOO_LONG"
    )
    assert len(long_row["errors"][0]["value"]) <= 50  # offending value is truncated


def test_fr_02_06_one_row_reports_all_its_errors(client: TestClient, auth: dict[str, str]) -> None:
    p = preview(client, auth, "nope,,abc,zzz,,,,")
    cols = sorted(e["column"] for e in p["rows"][0]["errors"])
    assert cols == ["amount", "date", "description", "type"]


def test_fr_02_06_category_column_slug_or_name_is_user_set(
    client: TestClient, auth: dict[str, str]
) -> None:
    cats = client.get(f"{API}/categories", headers=auth).json()
    cats = cats["items"] if isinstance(cats, dict) else cats
    expense = next(c for c in cats if c["transaction_type"] == "expense")
    p = preview(
        client,
        auth,
        f"{YESTERDAY},a,100,expense,,,{expense['slug']},",
        f"{YESTERDAY},b,100,expense,,,{expense['name'].upper()},",
    )
    for row in p["rows"]:
        assert row["status"] == "valid"
        assert row["values"]["category"] == expense["slug"]
        assert row["values"]["category_status"] == "user_set" and row["prediction"] is None


def test_fr_02_06_semicolon_delimiter_bom_and_unknown_columns(
    client: TestClient, auth: dict[str, str]
) -> None:
    content = (
        f"﻿Date;Description;AMOUNT;Type;Bank Ref\n{YESTERDAY};Kopi;25.000;expense;R1\n"
    ).encode()
    r = upload(client, auth, content)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["summary"]["valid"] == 1 and p["rows"][0]["values"]["amount"] == "25000.00"
    assert p["warnings"] == [
        {
            "code": "UNKNOWN_COLUMNS",
            "message": "Unknown columns are ignored.",
            "columns": ["bank ref"],
        }
    ]


def test_fr_02_06_dates_without_time_use_the_users_timezone(
    client: TestClient, auth: dict[str, str]
) -> None:
    p = preview(client, auth, f"{YESTERDAY} 00:30,a,100,expense,,,,")
    value = p["rows"][0]["values"]["transaction_date"]
    assert value == f"{YESTERDAY}T00:30:00+07:00"


def test_17_2_text_hygiene_applies_to_csv_rows(client: TestClient, auth: dict[str, str]) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kartu 4111111111111111,100,expense,,,,")
    assert p["rows"][0]["values"]["description"] == "Kartu ****1111"


def test_fr_02_06_template_csv(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get(f"{API}/transactions/imports/template.csv", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert len(lines) == 4 and lines[0].startswith("date,description,amount,type")
    # The template itself must import cleanly (3 example rows).
    p = upload(client, auth, r.content)
    assert p.status_code == 201
    assert p.json()["summary"]["invalid"] == 0
    assert client.get(f"{API}/transactions/imports/template.csv").status_code == 401


# --- limits and file errors --------------------------------------------------------------------
def test_fr_02_10_file_level_errors(client: TestClient, auth: dict[str, str]) -> None:
    r = upload(client, auth, "café,x\n".encode("latin-1"))
    assert r.status_code == 422 and r.json()["code"] == "INVALID_ENCODING"
    r = upload(client, auth, b"")
    assert r.status_code == 422 and r.json()["code"] == "EMPTY_FILE"
    r = upload(client, auth, b"date,description,amount\n2026-01-01,x,1\n")
    assert r.status_code == 422 and r.json()["code"] == "MISSING_COLUMNS"
    r = client.post(f"{API}/transactions/imports", headers=auth)
    assert r.status_code == 422  # no file part


def test_fr_02_10_size_and_row_limits(client: TestClient, auth: dict[str, str]) -> None:
    big = b"date,description,amount,type\n" + b"x" * (5 * 1024 * 1024 + 1)
    r = upload(client, auth, big)
    assert r.status_code == 413 and r.json()["code"] == "FILE_TOO_LARGE"
    row = f"{YESTERDAY},x,1,expense\n"
    ok = "date,description,amount,type\n" + row * 5000
    r = upload(client, auth, ok.encode())
    assert r.status_code == 201 and r.json()["summary"]["row_count"] == 5000
    r = upload(client, auth, (ok + row).encode())
    assert r.status_code == 422 and r.json()["code"] == "TOO_MANY_ROWS"


def test_fr_02_06_import_requires_auth(client: TestClient) -> None:
    r = client.post(f"{API}/transactions/imports", files={"file": ("a.csv", b"x", "text/csv")})
    assert r.status_code == 401


# --- duplicates --------------------------------------------------------------------------------
def test_fr_02_14_duplicates_against_existing_and_within_file(
    client: TestClient, auth: dict[str, str]
) -> None:
    make(
        client,
        auth,
        description="Kopi Kenangan",
        amount="25000",
        transaction_date=YESTERDAY,
    )
    p = preview(
        client,
        auth,
        f"{YESTERDAY},Kopi Kenangan,25000,expense,,,,",  # existing, same local day
        f"{YESTERDAY},Bakso Pak Kumis,15000,expense,,,,",
        f"{YESTERDAY},Bakso Pak Kumis,15000,expense,,,,",  # earlier row of the same file
        f"{YESTERDAY},Bakso Pak Kumis,16000,expense,,,,",  # different amount
        f"{YESTERDAY} 10:00,Sate,20000,expense,,,,",
        f"{YESTERDAY} 10:05,Sate,20000,expense,,,,",  # within 10 minutes
        f"{YESTERDAY} 10:30,Sate,20000,expense,,,,",  # outside 10 minutes
    )
    status = {r["row_number"]: r["status"] for r in p["rows"]}
    assert status == {
        2: "duplicate",
        3: "valid",
        4: "duplicate",
        5: "valid",
        6: "valid",
        7: "duplicate",
        8: "valid",
    }
    rows = {r["row_number"]: r for r in p["rows"]}
    assert rows[2]["duplicate_of"] and rows[2]["duplicate_of_row"] is None
    assert rows[4]["duplicate_of_row"] == 3 and rows[4]["duplicate_of"] is None
    assert p["summary"] == {"row_count": 7, "valid": 4, "invalid": 0, "duplicate": 3}


def test_fr_02_14_commit_skips_duplicates_by_default_or_flags_them(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = (
        f"{YESTERDAY},Bakso Pak Kumis,15000,expense,,,,",
        f"{YESTERDAY},Bakso Pak Kumis,15000,expense,,,,",
    )
    p1 = preview(client, auth, *rows)
    r = commit(client, auth, p1["import_id"])
    assert r.status_code == 200
    assert r.json() == {"committed_count": 1, "skipped_invalid": 0, "skipped_duplicates": 1}

    p2 = preview(client, auth, *rows)  # both now duplicate an existing transaction
    assert p2["summary"]["duplicate"] == 2
    r = commit(client, auth, p2["import_id"], skip_duplicates=False)
    assert r.json()["committed_count"] == 2 and r.json()["skipped_duplicates"] == 0
    flagged = tx_for_import(engine, p2["import_id"])
    assert len(flagged) == 2 and all(t.possible_duplicate_of is not None for t in flagged)


def test_fr_02_14_file_duplicates_inserted_on_request_point_at_the_first_row(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(
        client,
        auth,
        f"{YESTERDAY},Rare Item,777,expense,,,,",
        f"{YESTERDAY},Rare Item,777,expense,,,,",
    )
    assert p["rows"][1]["duplicate_of_row"] == 2
    commit(client, auth, p["import_id"], skip_duplicates=False)
    got = tx_for_import(engine, p["import_id"])
    assert sorted(t.possible_duplicate_of is None for t in got) == [False, True]


# --- commit ------------------------------------------------------------------------------------
def test_fr_02_07_strict_commit_with_invalid_rows_is_422_and_writes_nothing(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, *GOOD)
    before = count_tx(engine)
    r = commit(client, auth, p["import_id"], mode="strict")
    assert r.status_code == 422 and r.json()["code"] == "IMPORT_HAS_INVALID_ROWS"
    r = commit(client, auth, p["import_id"])  # strict is the default
    assert r.status_code == 422
    assert count_tx(engine) == before
    # The import is still committable in skip_invalid mode: the failed attempt changed nothing.
    ok = commit(client, auth, p["import_id"], mode="skip_invalid")
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"committed_count": 2, "skipped_invalid": 1, "skipped_duplicates": 0}


def test_fr_02_07_commit_writes_rows_events_and_clears_staging(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, *GOOD[:2])
    r = commit(client, auth, p["import_id"], mode="skip_invalid")
    assert r.status_code == 200
    assert r.json() == {"committed_count": 2, "skipped_invalid": 0, "skipped_duplicates": 0}
    got = tx_for_import(engine, p["import_id"])
    assert [(t.description, str(t.amount), t.source) for t in got] == [
        ("Gaji", "1500000.00", "csv"),
        ("Kopi Kenangan", "25000.00", "csv"),
    ]
    assert all(t.category_status == "needs_review" for t in got)
    with engine.connect() as conn:
        events = conn.execute(
            text(
                "SELECT event_type, count(*) FROM outbox_events WHERE payload->'data'->>'import_id' = :i "
                "OR aggregate_id = CAST(:i AS uuid) GROUP BY event_type"
            ),
            {"i": p["import_id"]},
        ).all()
        imp = conn.execute(
            text(
                "SELECT status, committed_count, commit_mode, committed_at IS NOT NULL, "
                "staged_rows::text, row_count FROM transaction_imports WHERE id = :i"
            ),
            {"i": p["import_id"]},
        ).one()
    assert dict(events) == {"transaction.created": 2, "import.committed": 1}
    assert tuple(imp) == ("committed", 2, "skip_invalid", True, "{}", 2)
    after = client.get(f"{API}/transactions/imports/{p['import_id']}", headers=auth).json()
    assert (
        after["status"] == "committed"
        and after["rows"] == []
        and after["summary"]["row_count"] == 2
    )
    # Imported rows are normal transactions in the list API.
    listed = client.get(f"{API}/transactions?limit=200", headers=auth).json()["items"]
    imported = [t for t in listed if t["source"] == "csv"]
    assert len(imported) == 2 and all(t["import_id"] == p["import_id"] for t in imported)


def test_fr_02_07_category_overrides(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    cats = client.get(f"{API}/categories", headers=auth).json()
    cats = cats["items"] if isinstance(cats, dict) else cats
    slug = next(c["slug"] for c in cats if c["transaction_type"] == "expense")
    p = preview(
        client, auth, f"{YESTERDAY},Kopi,100,expense,,,,", f"{YESTERDAY},Teh,200,expense,,,,"
    )
    r = commit(client, auth, p["import_id"], category_overrides={"2": slug})
    assert r.status_code == 200
    got = {t.description: t for t in tx_for_import(engine, p["import_id"])}
    assert got["Kopi"].category_status == "user_set"
    assert got["Teh"].category_status == "needs_review"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"2": "nonexistent"}, "UNKNOWN_CATEGORY"),
        ({"2": "salary"}, "CATEGORY_TYPE_MISMATCH"),
        ({"99": "food_beverage"}, "UNKNOWN_ROW"),
        ({"abc": "food_beverage"}, "UNKNOWN_ROW"),
        ({"3": "food_beverage"}, "UNKNOWN_ROW"),  # row 3 is invalid
    ],
)
def test_fr_02_07_bad_override_fails_everything(
    client: TestClient,
    auth: dict[str, str],
    engine: Engine,
    overrides: dict[str, str],
    code: str,
) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kopi,100,expense,,,,", "bad,x,1,expense,,,,")
    before = count_tx(engine)
    r = commit(client, auth, p["import_id"], mode="skip_invalid", category_overrides=overrides)
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["code"] == code
    assert r.json()["errors"][0]["field"].startswith("category_overrides.")
    assert count_tx(engine) == before


def test_fr_02_07_commit_is_atomic_on_db_error(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(
        client, auth, f"{YESTERDAY},Kopi,100,expense,,,,", f"{YESTERDAY},Teh,200,expense,,,,"
    )
    before = count_tx(engine)
    with engine.begin() as conn:  # force the second INSERT to fail: block the outbox table
        conn.execute(
            text(
                "ALTER TABLE outbox_events ADD CONSTRAINT boom CHECK (event_type <> 'import.committed') NOT VALID"
            )
        )
    try:
        r = commit(client, auth, p["import_id"])
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE outbox_events DROP CONSTRAINT boom"))
    assert r.status_code == 500
    assert count_tx(engine) == before  # nothing persisted
    with engine.connect() as conn:
        status = conn.execute(
            text("SELECT status FROM transaction_imports WHERE id = :i"), {"i": p["import_id"]}
        ).scalar_one()
        events = conn.execute(
            text("SELECT count(*) FROM outbox_events WHERE payload->'data'->>'import_id' = :i"),
            {"i": p["import_id"]},
        ).scalar_one()
    assert status == "previewed" and events == 0
    assert commit(client, auth, p["import_id"]).status_code == 200  # retry works


def test_fr_02_08_committed_expired_and_discarded_are_not_committable(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kopi,100,expense,,,,")
    assert commit(client, auth, p["import_id"]).status_code == 200
    again = commit(client, auth, p["import_id"])
    assert again.status_code == 409 and again.json()["code"] == "IMPORT_NOT_COMMITTABLE"

    q = preview(client, auth, f"{YESTERDAY},Teh,100,expense,,,,")
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE transaction_imports SET expires_at = now() - interval '1 minute' WHERE id = :i"
            ),
            {"i": q["import_id"]},
        )
    expired = commit(client, auth, q["import_id"])
    assert expired.status_code == 409 and expired.json()["code"] == "IMPORT_NOT_COMMITTABLE"

    d = preview(client, auth, f"{YESTERDAY},Susu,100,expense,,,,")
    assert (
        client.delete(f"{API}/transactions/imports/{d['import_id']}", headers=auth).status_code
        == 204
    )
    assert commit(client, auth, d["import_id"]).status_code == 404
    assert (
        client.get(f"{API}/transactions/imports/{d['import_id']}", headers=auth).status_code == 404
    )
    # A committed import is history and cannot be discarded.
    r = client.delete(f"{API}/transactions/imports/{p['import_id']}", headers=auth)
    assert r.status_code == 409


def test_13_1_5_commit_requires_idempotency_key_and_replays(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kopi,100,expense,,,,")
    url = f"{API}/transactions/imports/{p['import_id']}/commit"
    r = client.post(url, json={}, headers=auth)
    assert r.status_code == 400 and r.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    first = commit(client, auth, p["import_id"], key="import-key-0001")
    again = commit(client, auth, p["import_id"], key="import-key-0001")
    assert first.status_code == again.status_code == 200
    assert again.headers["Idempotent-Replayed"] == "true" and again.json() == first.json()
    assert len(tx_for_import(engine, p["import_id"])) == 1
    other_body = commit(client, auth, p["import_id"], key="import-key-0001", mode="skip_invalid")
    assert other_body.status_code == 409 and other_body.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_13_1_5_concurrent_commits_with_different_keys_insert_once(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kopi,100,expense,,,,")
    results: list[int] = []

    def go() -> None:
        results.append(commit(client, auth, p["import_id"]).status_code)

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 409, 409, 409]
    assert len(tx_for_import(engine, p["import_id"])) == 1


def test_fr_02_09_reupload_of_committed_file_warns(
    client: TestClient, auth: dict[str, str]
) -> None:
    content = csv_bytes(f"{YESTERDAY},Kopi unik,100,expense,,,,")
    first = upload(client, auth, content).json()
    assert first["warnings"] == []
    again_before_commit = upload(client, auth, content).json()
    assert again_before_commit["warnings"] == []  # only a *committed* import counts
    assert commit(client, auth, first["import_id"]).status_code == 200
    again = upload(client, auth, content)
    assert again.status_code == 201  # a warning, not an error
    assert [w["code"] for w in again.json()["warnings"]] == ["FILE_ALREADY_IMPORTED"]
    other_user = signup(client)
    assert upload(client, other_user, content).json()["warnings"] == []


def test_fr_02_06_large_preview_is_paginated(client: TestClient, auth: dict[str, str]) -> None:
    rows = [f"{YESTERDAY},Item {i},{i + 1},expense,,,," for i in range(1200)]
    p = preview(client, auth, *rows)
    assert len(p["rows"]) == 500 and p["next_cursor"] and p["summary"]["row_count"] == 1200
    seen = [r["row_number"] for r in p["rows"]]
    cursor = p["next_cursor"]
    pages = 1
    while cursor:
        r = client.get(
            f"{API}/transactions/imports/{p['import_id']}",
            params={"cursor": cursor},
            headers=auth,
        )
        assert r.status_code == 200
        page = r.json()
        seen += [x["row_number"] for x in page["rows"]]
        cursor, pages = page["next_cursor"], pages + 1
    assert seen == list(range(2, 1202)) and pages == 3
    bad = client.get(
        f"{API}/transactions/imports/{p['import_id']}", params={"cursor": "junk"}, headers=auth
    )
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_CURSOR"


def test_fr_02_07_commit_5000_rows_in_one_request(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    rows = [f"{YESTERDAY} 10:{i % 60:02d},Item unik {i},{i + 1},expense,,,," for i in range(5000)]
    p = preview(client, auth, *rows)
    assert p["summary"]["valid"] + p["summary"]["duplicate"] == 5000
    r = commit(client, auth, p["import_id"], skip_duplicates=False)
    assert r.status_code == 200 and r.json()["committed_count"] == 5000
    assert len(tx_for_import(engine, p["import_id"])) == 5000


# --- isolation and privacy ---------------------------------------------------------------------
def test_fr_02_01_other_users_imports_are_404_everywhere(
    client: TestClient, auth: dict[str, str], engine: Engine
) -> None:
    p = preview(client, auth, f"{YESTERDAY},Kopi,100,expense,,,,")
    intruder = signup(client)
    iid = p["import_id"]
    base = f"{API}/transactions/imports/{iid}"
    assert client.get(base, headers=intruder).status_code == 404
    assert commit(client, intruder, iid).status_code == 404
    assert client.delete(base, headers=intruder).status_code == 404
    assert client.get(base, headers=auth).status_code == 200  # untouched
    assert len(tx_for_import(engine, iid)) == 0


def test_17_3_imports_never_log_cell_contents(
    client: TestClient, auth: dict[str, str], log_stream: Any
) -> None:
    secret = "RAHASIA-BANK-XYZ"
    p = preview(
        client,
        auth,
        f"{YESTERDAY},{secret},123457,expense,,{secret},,{secret}",
        f"bad,{secret},1,expense,,,,",
    )
    commit(client, auth, p["import_id"], mode="skip_invalid")
    logs = log_stream.getvalue()
    assert secret not in logs and "123457" not in logs
