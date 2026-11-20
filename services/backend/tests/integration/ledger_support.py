"""Seed a hand-written or generated ledger straight into the database (no API, no ML)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from app.core.ids import new_uuid7
from sqlalchemy import Engine, text


def category_ids(engine: Engine) -> dict[str, uuid.UUID]:
    with engine.connect() as conn:
        return {slug: cid for slug, cid in conn.execute(text("SELECT slug, id FROM categories"))}


def seed_transactions(
    engine: Engine, user_id: uuid.UUID, rows: Iterable[Mapping[str, Any]]
) -> None:
    """Insert rows with keys: at, type, amount, category, merchant, key, method (+ optional has_time)."""
    ids = category_ids(engine)
    values = [
        {
            "id": new_uuid7(),
            "user_id": user_id,
            "type": r["type"],
            "amount": Decimal(r["amount"]),
            "description": r.get("description") or r.get("merchant") or "seed",
            "merchant": r.get("merchant"),
            "key": r.get("key", ""),
            "at": r["at"]
            if isinstance(r["at"], dt.datetime)
            else dt.datetime.fromisoformat(r["at"]),
            "has_time": r.get("has_time", True),
            "method": r.get("method", "other"),
            "category_id": ids[r["category"]],
            "status": r.get("status", "user_set"),
        }
        for r in rows
    ]
    if not values:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (id, user_id, transaction_type, amount, description, "
                "merchant, merchant_key, transaction_date, has_time, payment_method, category_id, "
                "category_status, source, version, created_at, updated_at) VALUES (:id, :user_id, :type, :amount, "
                ":description, :merchant, :key, :at, :has_time, :method, :category_id, :status, "
                "'manual', 1, now(), now())"
            ),
            values,
        )


def configure_user(engine: Engine, user_id: uuid.UUID, **fields: Any) -> None:
    allowed = {
        "timezone",
        "budget_period_start_day",
        "opening_balance",
        "pending_period_start_day",
        "pending_period_start_effective",
    }
    assert set(fields) <= allowed, set(fields) - allowed
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE users SET {sets} WHERE id = :id"), {**fields, "id": user_id})  # noqa: S608


def set_budget(engine: Engine, user_id: uuid.UUID, limit: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO budgets (id, user_id, category_id, limit_amount, created_at, "
                "updated_at) VALUES (:id, :u, NULL, :limit, now(), now())"
            ),
            {"id": new_uuid7(), "u": user_id, "limit": Decimal(limit)},
        )
