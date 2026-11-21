"""Stored forecasts and the history queries behind them (PRD 7.7, 12.2).

Every method takes ``user_id`` first and filters on it. Sums are computed in SQL; the caller turns
them into floats only for the forecast arithmetic (``ml.forecasting``).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select, text

from app.models import Forecast, RecurringSeries, RecurringSeriesTransaction, Transaction
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

    @staticmethod
    def _linked_to_recurring(user_id: uuid.UUID, min_confidence: float) -> ColumnElement[bool]:
        """Expenses linked to a series that splits the forecast (7.7.1): confident or confirmed."""
        return exists().where(
            RecurringSeriesTransaction.transaction_id == Transaction.id,
            RecurringSeries.id == RecurringSeriesTransaction.series_id,
            RecurringSeries.user_id == user_id,
            RecurringSeries.transaction_type == "expense",
            and_(
                RecurringSeries.status != "user_rejected",
                or_(
                    RecurringSeries.status == "user_confirmed",
                    RecurringSeries.confidence >= min_confidence,
                ),
            ),
        )

    def spent_between(
        self,
        user_id: uuid.UUID,
        lo: dt.datetime,
        hi: dt.datetime,
        category_id: uuid.UUID | None,
        exclude_recurring_min: float | None = None,
    ) -> Decimal:
        """Expense total; with ``exclude_recurring_min`` the recurring-linked ones are left out."""
        stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "expense",
            Transaction.transaction_date >= lo,
            Transaction.transaction_date < hi,
        )
        if category_id is not None:
            stmt = stmt.where(Transaction.category_id == category_id)
        if exclude_recurring_min is not None:
            stmt = stmt.where(~self._linked_to_recurring(user_id, exclude_recurring_min))
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
        exclude_recurring_min: float | None = None,
    ) -> list[tuple[dt.date, float]]:
        """Expenses per local day from ``start`` to ``end`` inclusive, zero-filled.

        With ``exclude_recurring_min`` the expenses linked to a recurring series that splits the
        forecast (confidence at least that, or confirmed by the user) are left out (7.7.1)."""
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
                 AND (CAST(:rec AS numeric) IS NULL OR NOT EXISTS (
                       SELECT 1 FROM recurring_series_transactions l
                       JOIN recurring_series s ON s.id = l.series_id
                       WHERE l.transaction_id = t.id AND s.user_id = :user_id
                         AND s.transaction_type = 'expense' AND s.status <> 'user_rejected'
                         AND (s.status = 'user_confirmed'
                              OR s.confidence >= CAST(:rec AS numeric))))
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
                "rec": exclude_recurring_min,
            },
        )
        return [(day, float(spend)) for day, spend in rows]

    def changed_since(self, user_id: uuid.UUID, since: dt.datetime) -> bool:
        """FR-07.07: a transaction or a recurring series added or edited after ``since``?"""
        stmt = (
            select(Transaction.id)
            .where(Transaction.user_id == user_id, Transaction.updated_at > since)
            .limit(1)
        )
        if self.session.execute(stmt).first() is not None:
            return True
        series = select(RecurringSeries.id).where(
            RecurringSeries.user_id == user_id, RecurringSeries.updated_at > since
        )
        return self.session.execute(series.limit(1)).first() is not None
