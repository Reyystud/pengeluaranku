"""Recurring series and the transaction history the detector reads (PRD 7.8, 12.2).

Every method takes ``user_id`` first and filters on it. The link table has no ``user_id``, so it
is only ever reached through a series that is itself filtered by ``user_id``.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection, Sequence
from decimal import Decimal

from sqlalchemy import delete, func, select, text

from app.models import RecurringSeries, RecurringSeriesTransaction, Transaction
from app.repositories.base import ScopedRepository


class RecurringSeriesRepository(ScopedRepository[RecurringSeries]):
    model = RecurringSeries

    # -- series ----------------------------------------------------------------------------------
    def all(self, user_id: uuid.UUID) -> list[RecurringSeries]:
        stmt = (
            select(RecurringSeries)
            .where(RecurringSeries.user_id == user_id)
            .order_by(RecurringSeries.next_expected_date, RecurringSeries.merchant_key)
        )
        return list(self.session.execute(stmt).scalars())

    def delete_many(self, user_id: uuid.UUID, ids: Collection[uuid.UUID]) -> int:
        if not ids:
            return 0
        result = self.session.execute(
            delete(RecurringSeries).where(
                RecurringSeries.user_id == user_id, RecurringSeries.id.in_(list(ids))
            )
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    def changed_since(self, user_id: uuid.UUID, since: dt.datetime) -> bool:
        """Did a series change after ``since``? (forecast cache rule, FR-07.07)"""
        stmt = (
            select(RecurringSeries.id)
            .where(RecurringSeries.user_id == user_id, RecurringSeries.updated_at > since)
            .limit(1)
        )
        return self.session.execute(stmt).first() is not None

    # -- links -----------------------------------------------------------------------------------
    def linked_ids(
        self, user_id: uuid.UUID, series_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, set[uuid.UUID]]:
        if not series_ids:
            return {}
        rows = self.session.execute(
            select(RecurringSeriesTransaction.series_id, RecurringSeriesTransaction.transaction_id)
            .join(RecurringSeries, RecurringSeries.id == RecurringSeriesTransaction.series_id)
            .where(
                RecurringSeries.user_id == user_id,
                RecurringSeriesTransaction.series_id.in_(list(series_ids)),
            )
        )
        out: dict[uuid.UUID, set[uuid.UUID]] = {sid: set() for sid in series_ids}
        for sid, tid in rows:
            out[sid].add(tid)
        return out

    def link(
        self, user_id: uuid.UUID, series_id: uuid.UUID, transaction_ids: Collection[uuid.UUID]
    ) -> None:
        """Link transactions of this user to ``series_id`` (rows of other users are skipped)."""
        owned = select(Transaction.id).where(
            Transaction.user_id == user_id, Transaction.id.in_(list(transaction_ids))
        )
        for tid in self.session.execute(owned).scalars():
            self.session.add(RecurringSeriesTransaction(series_id=series_id, transaction_id=tid))
        self.session.flush()

    def unlink(
        self, user_id: uuid.UUID, series_id: uuid.UUID, transaction_ids: Collection[uuid.UUID]
    ) -> None:
        if not transaction_ids:
            return
        mine = select(RecurringSeries.id).where(
            RecurringSeries.user_id == user_id, RecurringSeries.id == series_id
        )
        self.session.execute(
            delete(RecurringSeriesTransaction).where(
                RecurringSeriesTransaction.series_id.in_(mine),
                RecurringSeriesTransaction.transaction_id.in_(list(transaction_ids)),
            )
        )

    def recent_amounts(
        self, user_id: uuid.UUID, series_ids: Collection[uuid.UUID], keep: int
    ) -> dict[uuid.UUID, list[Decimal]]:
        """The last ``keep`` linked amounts per series, oldest first."""
        if not series_ids:
            return {}
        rows = self.session.execute(
            text(
                """
                SELECT series_id, amount FROM (
                  SELECT l.series_id, t.amount,
                         row_number() OVER (PARTITION BY l.series_id
                                            ORDER BY t.transaction_date DESC, t.id DESC) AS rn,
                         t.transaction_date AS at
                  FROM recurring_series_transactions l
                  JOIN recurring_series s ON s.id = l.series_id
                  JOIN transactions t ON t.id = l.transaction_id AND t.user_id = s.user_id
                  WHERE s.user_id = :user_id AND l.series_id = ANY(:ids)
                ) ranked WHERE rn <= :keep ORDER BY series_id, at
                """
            ),
            {"user_id": user_id, "ids": list(series_ids), "keep": keep},
        )
        out: dict[uuid.UUID, list[Decimal]] = {sid: [] for sid in series_ids}
        for sid, amount in rows:
            out[sid].append(Decimal(amount))
        return out

    # -- detector input --------------------------------------------------------------------------
    def occurrences(
        self,
        user_id: uuid.UUID,
        tz_name: str,
        since: dt.datetime,
        merchant_keys: Sequence[str] | None = None,
    ) -> list[tuple[uuid.UUID, str, str | None, str, uuid.UUID, dt.date, Decimal]]:
        """``(id, merchant_key, merchant, type, category_id, local_date, amount)`` of income and
        expense transactions with a merchant key since ``since``."""
        local_day = func.date(func.timezone(tz_name, Transaction.transaction_date))
        stmt = (
            select(
                Transaction.id,
                Transaction.merchant_key,
                Transaction.merchant,
                Transaction.transaction_type,
                Transaction.category_id,
                local_day,
                Transaction.amount,
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type.in_(("income", "expense")),
                Transaction.merchant_key != "",
                Transaction.transaction_date >= since,
            )
            .order_by(Transaction.transaction_date, Transaction.id)
        )
        if merchant_keys is not None:
            stmt = stmt.where(Transaction.merchant_key.in_(list(merchant_keys)))
        return [(*row,) for row in self.session.execute(stmt)]

    def known_keys_of(self, user_id: uuid.UUID, transaction_ids: Collection[uuid.UUID]) -> set[str]:
        """Merchant keys of these transactions that already have a series (FR-08.06)."""
        if not transaction_ids:
            return set()
        stmt = (
            select(Transaction.merchant_key)
            .join(
                RecurringSeries,
                (RecurringSeries.user_id == Transaction.user_id)
                & (RecurringSeries.merchant_key == Transaction.merchant_key)
                & (RecurringSeries.transaction_type == Transaction.transaction_type),
            )
            .where(Transaction.user_id == user_id, Transaction.id.in_(list(transaction_ids)))
            .distinct()
        )
        return set(self.session.execute(stmt).scalars())
