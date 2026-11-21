"""The demo seeder (PRD 19.1 `make seed-demo`): selection, date shift, CSV contract, API flow."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import httpx
import pytest
from app import seed_demo
from app.core.csvparse import read_table

HEADER = [
    "date", "description", "amount", "type", "payment_method", "merchant", "category", "notes",
    "transaction_id", "user_id", "archetype", "true_category", "true_merchant", "is_anomaly",
    "anomaly_type", "anomaly_severity", "recurring_series_id", "has_time",
]  # fmt: skip


def row(user: str, archetype: str, date: str, **over: str) -> dict[str, str]:
    base = dict.fromkeys(HEADER, "")
    base.update(
        date=date, description="KOPI", amount="25000.00", type="expense", payment_method="cash",
        merchant="Kopi", transaction_id=f"{user}-{date}", user_id=user, archetype=archetype,
        true_category="food_beverage", true_merchant="Kopi", is_anomaly="False", has_time="False",
    )  # fmt: skip
    base.update(over)
    return base


@pytest.fixture
def source(tmp_path: Path) -> Path:
    rows = [row("u-a", seed_demo.ARCHETYPE, f"2025-01-{d:02d}") for d in range(1, 6)]
    rows += [row("u-b", seed_demo.ARCHETYPE, f"2025-01-{d:02d}") for d in range(1, 4)]
    rows += [row("u-c", seed_demo.ARCHETYPE, f"2025-01-{d:02d}") for d in range(1, 8)]
    rows += [row("u-s", "student", f"2025-01-{d:02d}") for d in range(1, 20)]
    path = tmp_path / "transactions.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_fr_04_11_pick_user_is_the_median_of_the_archetype_and_deterministic(
    source: Path,
) -> None:
    assert seed_demo.pick_user(source) == "u-a"  # sizes 5, 3, 7 -> median 5; students ignored
    assert seed_demo.pick_user(source) == "u-a"
    with pytest.raises(SystemExit):
        seed_demo.pick_user(source, "freelancer")


def test_fr_04_11_week_shift_keeps_weekdays_and_ends_within_a_week_of_today() -> None:
    last, today = dt.date(2025, 12, 31), dt.date(2026, 11, 21)
    shift = seed_demo.week_shift(last, today)
    assert shift.days % 7 == 0 and (last + shift).weekday() == last.weekday()
    assert 0 <= (today - (last + shift)).days < 7
    assert seed_demo.week_shift(today, today) == dt.timedelta(0)


def test_fr_04_11_built_csv_is_a_valid_product_import_with_shifted_dates(source: Path) -> None:
    today = dt.date(2026, 11, 21)
    text, count = seed_demo.build_csv(source, "u-a", today)
    assert count == 5
    table = read_table(text, max_rows=5000)
    assert table.columns == list(seed_demo.COLUMNS)
    rows = list(csv.DictReader(text.splitlines(), delimiter=table.delimiter))
    assert {r["category"] for r in rows} == {"food_beverage"}  # pre-categorized history
    assert "user_id" not in rows[0] and "true_category" not in rows[0]
    last = max(dt.date.fromisoformat(r["date"][:10]) for r in rows)
    assert 0 <= (today - last).days < 7


def api(handler: dict[str, list[httpx.Response]]) -> httpx.MockTransport:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        key = f"{request.method} {request.url.path}"
        calls.append(key)
        if key.startswith("POST /api/v1/transactions/imports/") and key.endswith("/commit"):
            key = "COMMIT"
        return handler[key].pop(0)

    transport = httpx.MockTransport(respond)
    transport.calls = calls  # type: ignore[attr-defined]
    return transport


def test_fr_04_11_seed_registers_imports_and_commits(source: Path) -> None:
    token = {"access_token": "t"}
    transport = api(
        {
            "POST /api/v1/auth/register": [httpx.Response(201, json=token)],
            "GET /api/v1/transactions/count": [httpx.Response(200, json={"count": 0})],
            "POST /api/v1/transactions/imports": [
                httpx.Response(201, json={"import_id": "i-1", "summary": {"valid": 5}})
            ],
            "COMMIT": [httpx.Response(200, json={"committed_count": 5})],
        }
    )
    code = seed_demo.seed(
        "http://x", source, "d@example.com", "pw", dt.date(2026, 11, 21), transport
    )
    assert code == 0
    assert transport.calls[-1].endswith("/commit")  # type: ignore[attr-defined]


def test_fr_04_11_seed_is_idempotent_and_falls_back_to_login(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = api(
        {
            "POST /api/v1/auth/register": [httpx.Response(409, json={})],
            "POST /api/v1/auth/login": [httpx.Response(200, json={"access_token": "t"})],
            "GET /api/v1/transactions/count": [httpx.Response(200, json={"count": 12})],
        }
    )
    assert (
        seed_demo.seed("http://x", source, "d@example.com", "pw", dt.date.today(), transport) == 0
    )
    assert "nothing to do" in capsys.readouterr().out
    assert not any("imports" in c for c in transport.calls)  # type: ignore[attr-defined]


def test_fr_04_11_seed_stops_when_neither_register_nor_login_works(source: Path) -> None:
    transport = api(
        {
            "POST /api/v1/auth/register": [httpx.Response(409, json={})],
            "POST /api/v1/auth/login": [httpx.Response(401, json={})],
        }
    )
    with pytest.raises(SystemExit):
        seed_demo.seed("http://x", source, "d@example.com", "pw", dt.date.today(), transport)


def test_fr_04_11_main_requires_password_and_csv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, source: Path
) -> None:
    monkeypatch.delenv("DEMO_USER_PASSWORD", raising=False)
    assert seed_demo.main(["--csv", str(source)]) == 2
    monkeypatch.setenv("DEMO_USER_PASSWORD", "pw")
    assert seed_demo.main(["--csv", str(tmp_path / "missing.csv")]) == 2
