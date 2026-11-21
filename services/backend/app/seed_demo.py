"""``python -m app.seed_demo``: create the demo user and load 12 months of synthetic history.

Talks to a running backend through its public API (register or login, CSV import, commit), so it
exercises the same code as a real user. Source rows come from the generator's CSV
(``make data``); one generated user is picked deterministically. Dates are shifted by whole weeks
so the history ends in the current week. Output contains counts only, never row contents.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import statistics
import sys
import uuid
from pathlib import Path

import httpx

ARCHETYPE = "young_professional"
COLUMNS = (
    "date",
    "description",
    "amount",
    "type",
    "payment_method",
    "merchant",
    "category",
    "notes",
)


def pick_user(csv_path: Path, archetype: str = ARCHETYPE) -> str:
    """The median-sized user of ``archetype`` (ties broken by user id): deterministic."""
    counts: dict[str, int] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["archetype"] == archetype:
                counts[row["user_id"]] = counts.get(row["user_id"], 0) + 1
    if not counts:
        raise SystemExit(f"no {archetype} user in {csv_path}")
    median = statistics.median_low(counts.values())
    return sorted(u for u, n in counts.items() if n == median)[0]


def week_shift(last_date: dt.date, today: dt.date) -> dt.timedelta:
    """Whole weeks, so weekdays are preserved, putting ``last_date`` within 7 days before today."""
    return dt.timedelta(days=((today - last_date).days // 7) * 7)


def build_csv(csv_path: Path, user_id: str, today: dt.date) -> tuple[str, int]:
    """CSV text for the import API (product columns only) and its row count."""
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = [r for r in csv.DictReader(handle) if r["user_id"] == user_id]
    if not rows:
        raise SystemExit("selected user has no rows")
    last = max(dt.date.fromisoformat(r["date"][:10]) for r in rows)
    shift = week_shift(last, today)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for r in sorted(rows, key=lambda r: r["date"]):
        day = dt.date.fromisoformat(r["date"][:10]) + shift
        # The history is pre-categorized (as a user who has confirmed their data would be).
        values = {**r, "date": day.isoformat() + r["date"][10:], "category": r["true_category"]}
        writer.writerow([values[c] for c in COLUMNS])
    return out.getvalue(), len(rows)


def login_or_register(client: httpx.Client, email: str, password: str) -> str:
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "display_name": "Demo"},
    )
    if registered.status_code == 201:
        return str(registered.json()["access_token"])
    logged_in = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if logged_in.status_code != 200:
        raise SystemExit(
            f"could not register ({registered.status_code}) or log in ({logged_in.status_code})"
        )
    return str(logged_in.json()["access_token"])


def seed(
    base_url: str,
    csv_path: Path,
    email: str,
    password: str,
    today: dt.date,
    transport: httpx.BaseTransport | None = None,
) -> int:
    with httpx.Client(base_url=base_url, timeout=120, transport=transport) as client:
        token = login_or_register(client, email, password)
        client.headers["Authorization"] = f"Bearer {token}"
        existing = client.get("/api/v1/transactions/count")
        existing.raise_for_status()
        if int(existing.json().get("count", 0)) > 0:
            print("demo user already has transactions: nothing to do")
            return 0
        text, rows = build_csv(csv_path, pick_user(csv_path), today)
        preview = client.post(
            "/api/v1/transactions/imports",
            files={"file": ("demo.csv", text.encode(), "text/csv")},
        )
        preview.raise_for_status()
        body = preview.json()
        print(f"staged {rows} rows: {body['summary']}")
        commit = client.post(
            f"/api/v1/transactions/imports/{body['import_id']}/commit",
            json={"mode": "skip_invalid", "skip_duplicates": True},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        commit.raise_for_status()
        print(f"committed: {commit.json()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.seed_demo")
    parser.add_argument(
        "--base-url", default=os.environ.get("SEED_BASE_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument("--csv", type=Path, default=Path("data/synthetic/v1/transactions.csv"))
    parser.add_argument("--email", default=os.environ.get("DEMO_USER_EMAIL", "demo@example.com"))
    args = parser.parse_args(argv)
    password = os.environ.get("DEMO_USER_PASSWORD")
    if not password:
        print("DEMO_USER_PASSWORD is not set", file=sys.stderr)
        return 2
    if not args.csv.is_file():
        print(f"{args.csv} not found: run `make data` first", file=sys.stderr)
        return 2
    return seed(args.base_url, args.csv, args.email, password, dt.date.today())


if __name__ == "__main__":
    raise SystemExit(main())
