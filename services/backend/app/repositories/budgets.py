"""Budgets and their period snapshots (PRD 7.5, 12.2). Every method takes ``user_id`` first."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.models import Budget, BudgetPeriodSnapshot, Category, Transaction
from app.models.base import utcnow
from app.repositories.base import ScopedRepository


class BudgetRepository(ScopedRepository[Budget]):
    model = Budget

    def list_all(self, user_id: uuid.UUID) -> list[Budget]:
        """Overall budget first, then category budgets by category name."""
        stmt = (
            select(Budget)
            .outerjoin(Category, Category.id == Budget.category_id)
            .where(Budget.user_id == user_id)
            .order_by(Budget.category_id.is_not(None), Category.name, Budget.id)
        )
        return list(self.session.execute(stmt).scalars())

    def get_for_category(self, user_id: uuid.UUID, category_id: uuid.UUID | None) -> Budget | None:
        stmt = select(Budget).where(Budget.user_id == user_id)
        stmt = stmt.where(
            Budget.category_id.is_(None)
            if category_id is None
            else Budget.category_id == category_id
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def spent_by_category(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime
    ) -> dict[uuid.UUID, Decimal]:
        """Expense totals per category in ``[lo, hi)``; transfers and income never count (4.4)."""
        stmt = (
            select(Transaction.category_id, func.sum(Transaction.amount))
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "expense",
                Transaction.transaction_date >= lo,
                Transaction.transaction_date < hi,
            )
            .group_by(Transaction.category_id)
        )
        return {cid: Decimal(total) for cid, total in self.session.execute(stmt)}

    # -- snapshots (FR-05.08) ------------------------------------------------------------------
    def snapshots(
        self, user_id: uuid.UUID, budget_id: uuid.UUID, limit: int
    ) -> list[BudgetPeriodSnapshot]:
        stmt = (
            select(BudgetPeriodSnapshot)
            .where(
                BudgetPeriodSnapshot.user_id == user_id,
                BudgetPeriodSnapshot.budget_id == budget_id,
            )
            .order_by(BudgetPeriodSnapshot.period_id.desc())
            .limit(limit)
        )
        return list(self.session.execute(stmt).scalars())

    def write_snapshot(
        self,
        user_id: uuid.UUID,
        budget_id: uuid.UUID,
        period_id: dt.date,
        limit_amount: Decimal,
        spent: Decimal,
        utilization: Decimal,
    ) -> bool:
        """Insert once per (budget, period); returns False when it already existed."""
        stmt = (
            insert(BudgetPeriodSnapshot)
            .values(
                budget_id=budget_id,
                user_id=user_id,
                period_id=period_id,
                limit_amount=limit_amount,
                spent=spent,
                utilization=utilization,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["budget_id", "period_id"])
            .returning(BudgetPeriodSnapshot.budget_id)
        )
        return self.session.execute(stmt).first() is not None  # no row back = it existed
