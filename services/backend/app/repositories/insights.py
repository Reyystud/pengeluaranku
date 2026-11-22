"""Insights (PRD 7.9, 12.2). Every method takes ``user_id`` first."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from app.core.ids import new_uuid7
from app.models import Insight, Transaction
from app.models.base import utcnow
from app.repositories.base import ScopedRepository

if TYPE_CHECKING:
    from app.services.insight_rules import Candidate


class InsightRepository(ScopedRepository[Insight]):
    model = Insight

    def upsert(self, user_id: uuid.UUID, period_id: dt.date, candidates: list[Candidate]) -> int:
        """Insert or refresh one row per (rule, period, subject); returns how many were new.

        ``dismissed_at`` and ``created_at`` are never touched by a refresh, so a dismissed insight
        stays dismissed for the same subject and period (FR-09.04).
        """
        existing = set(
            self.session.execute(
                select(Insight.rule_id, Insight.subject_key).where(
                    Insight.user_id == user_id, Insight.period_id == period_id
                )
            ).all()
        )
        now = utcnow()
        for c in candidates:
            values = {
                "rule_version": c.rule_version,
                "severity": c.severity,
                "priority": c.priority,
                "title": c.title,
                "message": c.message,
                "message_key": c.message_key,
                "message_params": c.message_params,
                "evidence": c.evidence,
                "updated_at": now,
            }
            stmt = insert(Insight).values(
                id=new_uuid7(),
                user_id=user_id,
                rule_id=c.rule_id,
                period_id=period_id,
                subject_key=c.subject_key,
                created_at=now,
                **values,
            )
            self.session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["user_id", "rule_id", "period_id", "subject_key"], set_=values
                )
            )
        return sum(1 for c in candidates if (c.rule_id, c.subject_key) not in existing)

    def delete_stale(
        self, user_id: uuid.UUID, period_id: dt.date, keep: set[tuple[str, str]]
    ) -> int:
        """Remove open insights of the period whose rule no longer fires; dismissed ones stay."""
        stmt = delete(Insight).where(
            Insight.user_id == user_id,
            Insight.period_id == period_id,
            Insight.dismissed_at.is_(None),
        )
        if keep:
            stmt = stmt.where(tuple_(Insight.rule_id, Insight.subject_key).not_in(list(keep)))
        result = self.session.execute(stmt)
        return int(result.rowcount)  # type: ignore[attr-defined]

    def page(
        self,
        user_id: uuid.UUID,
        period_id: dt.date | None,
        include_dismissed: bool,
        limit: int,
    ) -> list[Insight]:
        stmt = select(Insight).where(Insight.user_id == user_id)
        if period_id is not None:
            stmt = stmt.where(Insight.period_id == period_id)
        if not include_dismissed:
            stmt = stmt.where(Insight.dismissed_at.is_(None))
        stmt = stmt.order_by(Insight.priority.desc(), Insight.created_at.desc(), Insight.id).limit(
            limit
        )
        return list(self.session.execute(stmt).scalars())

    def dismiss(self, user_id: uuid.UUID, id: uuid.UUID) -> Insight | None:
        stmt = (
            update(Insight)
            .where(Insight.user_id == user_id, Insight.id == id)
            .values(dismissed_at=func.coalesce(Insight.dismissed_at, utcnow()))
            .returning(Insight)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def small_purchases(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime, below: Decimal
    ) -> tuple[int, Decimal]:
        """Count and sum of this user's expenses under ``below`` in ``[lo, hi)`` (INS-06)."""
        stmt = select(func.count(), func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "expense",
            Transaction.transaction_date >= lo,
            Transaction.transaction_date < hi,
            Transaction.amount < below,
        )
        n, total = self.session.execute(stmt).one()
        return int(n), Decimal(total)
