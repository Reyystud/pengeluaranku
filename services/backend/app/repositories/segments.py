"""Behavior segment storage and the transaction rows its features need (PRD 12, FR-13).

Every method takes ``user_id`` first and filters by it (PRD 12.4).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Category, Transaction, UserSegment
from app.repositories.forecasts import ForecastRepository


class SegmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, user_id: uuid.UUID) -> UserSegment | None:
        stmt = select(UserSegment).where(UserSegment.user_id == user_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert(
        self,
        user_id: uuid.UUID,
        segment_id: str,
        traits: list[dict[str, Any]],
        model_version: str,
        computed_at: dt.datetime,
    ) -> None:
        values = {
            "user_id": user_id,
            "segment_id": segment_id,
            "traits": traits,
            "model_version": model_version,
            "computed_at": computed_at,
        }
        stmt = insert(UserSegment).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserSegment.user_id],
            set_={k: v for k, v in values.items() if k != "user_id"},
        )
        self.session.execute(stmt)

    def window_rows(
        self,
        user_id: uuid.UUID,
        lo: dt.datetime,
        hi: dt.datetime,
        recurring_min: float,
    ) -> list[tuple[dt.datetime, str, Any, str, bool]]:
        """(transaction_date, type, amount, category slug, linked to a recurring series) in
        ``[lo, hi)``; the recurring test is the one that splits the forecast (7.7.1)."""
        linked = ForecastRepository._linked_to_recurring(user_id, recurring_min)
        stmt = (
            select(
                Transaction.transaction_date,
                Transaction.transaction_type,
                Transaction.amount,
                Category.slug,
                linked,
            )
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_date >= lo,
                Transaction.transaction_date < hi,
            )
        )
        return [tuple(r) for r in self.session.execute(stmt).all()]  # type: ignore[misc]
