"""Stored forecasts and the history queries behind them (PRD 7.7, 12.2).

Every method takes ``user_id`` first and filters on it. Sums are computed in SQL; the caller turns
them into floats only for the forecast arithmetic (``ml.forecasting``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import delete, func, select, text

from app.models import Forecast, Transaction
from app.repositories.base import ScopedRepository


class ForecastRepository(ScopedRepository[Forecast]):
    model = Forecast

    # -- stored rows ---------------------------------------------------------------------------
    def latest(
        self, user_id: uuid.UUID, period_id: dt.date, category_id: uuid.UUID | None
    ) -> Forecast | None:
        stmt = (
            select(Forecast)
            .where(Forecast.user_id == user_id, Forecast.period_id == period_id)
            .where(
                Forecast.category_id.is_(None)
                if category_id is None
                else Forecast.category_id == category_id
            )
            .order_by(Forecast.as_of.desc(), Forecast.id.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def prune(
        self, user_id: uuid.UUID, period_id: dt.date, category_id: uuid.UUID | None, keep: int
    ) -> int:
        """Keep the newest ``keep`` forecasts of one (period, category) series (PRD 12)."""
        same = (
            Forecast.user_id == user_id,
            Forecast.period_id == period_id,
            Forecast.category_id.is_(None)
            if category_id is None
            else Forecast.category_id == category_id,
        )
        newest = (
            select(Forecast.id)
            .where(*same)
            .order_by(Forecast.as_of.desc(), Forecast.id.desc())
            .limit(keep)
        )
        result = self.session.execute(
            delete(Forecast).where(*same, Forecast.id.not_in(newest.scalar_subquery()))
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    def count_series(
        self, user_id: uuid.UUID, period_id: dt.date, category_id: uuid.UUID | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(Forecast)
            .where(Forecast.user_id == user_id, Forecast.period_id == period_id)
            .where(
                Forecast.category_id.is_(None)
                if category_id is None
                else Forecast.category_id == category_id
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    # -- inputs --------------------------------------------------------------------------------
    def first_local_date(self, user_id: uuid.UUID, tz_name: str) -> dt.date | None:
        stmt = text(
            "SELECT min((transaction_date AT TIME ZONE :tz)::date) FROM transactions "
            "WHERE user_id = :user_id"
        )
        value = self.session.execute(stmt, {"user_id": user_id, "tz": tz_name}).scalar_one()
        return value  # type: ignore[no-any-return]

    def expense_count(self, user_id: uuid.UUID, category_id: uuid.UUID | None) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.user_id == user_id, Transaction.transaction_type == "expense")
        )
        if category_id is not None:
            stmt = stmt.where(Transaction.category_id == category_id)
        return int(self.session.execute(stmt).scalar_one())

    def spent_between(
        self,
        user_id: uuid.UUID,
        lo: dt.datetime,
        hi: dt.datetime,
        category_id: uuid.UUID | None,
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "expense",
            Transaction.transaction_date >= lo,
            Transaction.transaction_date < hi,
        )
        if category_id is not None:
            stmt = stmt.where(Transaction.category_id == category_id)
        return Decimal(self.session.execute(stmt).scalar_one())

    def daily_spend(
        self,
        user_id: uuid.UUID,
        tz_name: str,
        start: dt.date,
        end: dt.date,
        lo: dt.datetime,
        hi: dt.datetime,
        category_id: uuid.UUID | None,
    ) -> list[tuple[dt.date, float]]:
        """Expenses per local day from ``start`` to ``end`` inclusive, zero-filled."""
        rows = self.session.execute(
            text(
                """
                SELECT g.d::date AS day, COALESCE(SUM(t.amount), 0) AS spend
                FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day')
                     AS g(d)
                LEFT JOIN transactions t
                  ON t.user_id = :user_id
                 AND t.transaction_type = 'expense'
                 AND t.transaction_date >= :lo AND t.transaction_date < :hi
                 AND (t.transaction_date AT TIME ZONE :tz)::date = g.d::date
                 AND (CAST(:cat AS uuid) IS NULL OR t.category_id = CAST(:cat AS uuid))
                GROUP BY g.d
                ORDER BY g.d
                """
            ),
            {
                "user_id": user_id,
                "tz": tz_name,
                "start": start,
                "end": end,
                "lo": lo,
                "hi": hi,
                "cat": category_id,
            },
        )
        return [(day, float(spend)) for day, spend in rows]

    def changed_since(self, user_id: uuid.UUID, since: dt.datetime) -> bool:
        """FR-07.07: has the user added or edited a transaction after ``since``?"""
        stmt = (
            select(Transaction.id)
            .where(Transaction.user_id == user_id, Transaction.updated_at > since)
            .limit(1)
        )
        return self.session.execute(stmt).first() is not None
