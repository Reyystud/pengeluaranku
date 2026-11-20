"""Read-only aggregation queries for the dashboard (PRD 7.4, 12.4).

Everything is computed in SQL (``SUM ... FILTER``, ``GROUP BY``, window sums) so a figure on the
dashboard is the same number a direct query over ``transactions`` returns. Every method takes
``user_id`` first and filters on it. Transfers never count as income or expense (4.4).

Ranges are inclusive local dates. They are turned into a half-open ``timestamptz`` interval in the
user's time zone, which keeps the ``(user_id, transaction_date)`` index usable; day buckets use
``transaction_date AT TIME ZONE tz`` (4.2).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.orm import Session

from app.models import Budget, Category, Transaction

ZERO = Decimal("0.00")
_DAY = dt.timedelta(days=1)


@dataclass(frozen=True)
class Flow:
    income: Decimal
    expenses: Decimal
    income_count: int
    expense_count: int


@dataclass(frozen=True)
class CategoryRow:
    slug: str
    name: str
    amount: Decimal
    count: int


@dataclass(frozen=True)
class MerchantRow:
    merchant_key: str
    display: str
    amount: Decimal
    count: int


@dataclass(frozen=True)
class MethodRow:
    payment_method: str
    amount: Decimal
    count: int


@dataclass(frozen=True)
class BucketRow:
    start: dt.date
    end: dt.date
    expenses: Decimal
    cumulative: Decimal


def bounds_to_utc(start: dt.date, end: dt.date, tz: ZoneInfo) -> tuple[dt.datetime, dt.datetime]:
    """Inclusive local dates -> ``[lo, hi)`` instants."""
    lo = dt.datetime.combine(start, dt.time.min, tzinfo=tz)
    hi = dt.datetime.combine(end + _DAY, dt.time.min, tzinfo=tz)
    return lo, hi


class AnalyticsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _in_range(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime
    ) -> tuple[ColumnElement[bool], ...]:
        """Conditions for this user's expenses in ``[lo, hi)``."""
        return (
            Transaction.user_id == user_id,
            Transaction.transaction_type == "expense",
            Transaction.transaction_date >= lo,
            Transaction.transaction_date < hi,
        )

    # -- FR-04.01 ----------------------------------------------------------------------------
    def flows_until(self, user_id: uuid.UUID, until: dt.datetime) -> Flow:
        """All-time income and expenses up to ``until`` (for the balance)."""
        return self._flow(user_id, None, until, inclusive=True)

    # -- FR-04.02..04 ------------------------------------------------------------------------
    def flows_between(self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime) -> Flow:
        return self._flow(user_id, lo, hi)

    def _flow(
        self,
        user_id: uuid.UUID,
        lo: dt.datetime | None,
        hi: dt.datetime,
        *,
        inclusive: bool = False,
    ) -> Flow:
        income = Transaction.transaction_type == "income"
        expense = Transaction.transaction_type == "expense"
        stmt = select(
            func.coalesce(func.sum(Transaction.amount).filter(income), ZERO),
            func.coalesce(func.sum(Transaction.amount).filter(expense), ZERO),
            func.count().filter(income),
            func.count().filter(expense),
        ).where(
            Transaction.user_id == user_id,
            Transaction.transaction_date <= hi if inclusive else Transaction.transaction_date < hi,
        )
        if lo is not None:
            stmt = stmt.where(Transaction.transaction_date >= lo)
        inc, exp, inc_n, exp_n = self.session.execute(stmt).one()
        return Flow(Decimal(inc), Decimal(exp), int(inc_n), int(exp_n))

    # -- FR-04.05 ----------------------------------------------------------------------------
    def category_breakdown(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime
    ) -> list[CategoryRow]:
        total = func.sum(Transaction.amount)
        stmt = (
            select(Category.slug, Category.name, total, func.count())
            .select_from(Transaction)
            .where(*self._in_range(user_id, lo, hi))
            .join(Category, Category.id == Transaction.category_id)
            .group_by(Category.slug, Category.name)
            .order_by(total.desc(), Category.slug)
        )
        return [
            CategoryRow(slug, name, Decimal(amount), int(n))
            for slug, name, amount, n in self.session.execute(stmt)
        ]

    # -- FR-04.08 ----------------------------------------------------------------------------
    def top_merchants(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime, limit: int
    ) -> list[MerchantRow]:
        """Top merchants by expense. The display name is the most recent one used for that key."""
        rows = self.session.execute(
            text(
                """
                SELECT merchant_key,
                       (array_agg(COALESCE(NULLIF(merchant, ''), description)
                                  ORDER BY transaction_date DESC, id DESC))[1] AS display,
                       SUM(amount) AS amount,
                       COUNT(*) AS n
                FROM transactions
                WHERE user_id = :user_id
                  AND transaction_type = 'expense'
                  AND merchant_key <> ''
                  AND transaction_date >= :lo AND transaction_date < :hi
                GROUP BY merchant_key
                ORDER BY SUM(amount) DESC, merchant_key
                LIMIT :limit
                """
            ),
            {"user_id": user_id, "lo": lo, "hi": hi, "limit": limit},
        )
        return [MerchantRow(k, d, Decimal(a), int(n)) for k, d, a, n in rows]

    # -- FR-04.09 ----------------------------------------------------------------------------
    def payment_methods(
        self, user_id: uuid.UUID, lo: dt.datetime, hi: dt.datetime
    ) -> list[MethodRow]:
        total = func.sum(Transaction.amount)
        stmt = (
            select(Transaction.payment_method, total, func.count())
            .where(*self._in_range(user_id, lo, hi))
            .group_by(Transaction.payment_method)
            .order_by(total.desc(), Transaction.payment_method)
        )
        return [MethodRow(m, Decimal(a), int(n)) for m, a, n in self.session.execute(stmt)]

    # -- FR-04.06 ----------------------------------------------------------------------------
    def expense_buckets(
        self,
        user_id: uuid.UUID,
        tz: ZoneInfo,
        buckets: list[tuple[dt.date, dt.date]],
    ) -> list[BucketRow]:
        """Expenses per (inclusive, local) bucket, zero-filled, with a running total.

        The bucket list is generated by the caller (days, Monday weeks, or budget periods), so the
        aggregation itself stays in SQL for every granularity.
        """
        if not buckets:
            return []
        lo, _ = bounds_to_utc(buckets[0][0], buckets[0][1], tz)
        _, hi = bounds_to_utc(buckets[-1][0], buckets[-1][1], tz)
        rows = self.session.execute(
            text(
                """
                WITH b AS (
                  SELECT s AS bucket_start, e AS bucket_end, i AS idx
                  FROM unnest(CAST(:starts AS date[]), CAST(:ends AS date[]))
                       WITH ORDINALITY AS t(s, e, i)
                ), agg AS (
                  SELECT b.idx, COALESCE(SUM(t.amount), 0) AS expenses
                  FROM b
                  LEFT JOIN transactions t
                    ON t.user_id = :user_id
                   AND t.transaction_type = 'expense'
                   AND t.transaction_date >= :lo AND t.transaction_date < :hi
                   AND (t.transaction_date AT TIME ZONE :tz)::date
                       BETWEEN b.bucket_start AND b.bucket_end
                  GROUP BY b.idx
                )
                SELECT b.bucket_start, b.bucket_end, agg.expenses,
                       SUM(agg.expenses) OVER (ORDER BY b.idx) AS cumulative
                FROM b JOIN agg USING (idx)
                ORDER BY b.idx
                """
            ),
            {
                "user_id": user_id,
                "tz": tz.key,
                "lo": lo,
                "hi": hi,
                "starts": [s for s, _ in buckets],
                "ends": [e for _, e in buckets],
            },
        )
        return [BucketRow(s, e, Decimal(x), Decimal(c)) for s, e, x, c in rows]

    # -- other dashboard inputs --------------------------------------------------------------
    def review_queue_count(self, user_id: uuid.UUID) -> int:
        """FR-03.05: rows with a suggested or unresolved category."""
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.category_status.in_(("suggested", "needs_review")),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def overall_budget_limit(self, user_id: uuid.UUID) -> Decimal | None:
        """The overall (all categories) monthly limit, if the user set one (FR-05)."""
        stmt = select(Budget.limit_amount).where(
            Budget.user_id == user_id, Budget.category_id.is_(None)
        )
        value = self.session.execute(stmt).scalar_one_or_none()
        return None if value is None else Decimal(value)
