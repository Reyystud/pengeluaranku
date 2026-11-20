"""Transaction queries. Every public method takes ``user_id`` first and filters by it (PRD 12.4)."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select, tuple_, update

from app.core.cursor import Cursor
from app.models import Transaction
from app.repositories.base import ScopedRepository

DUPLICATE_WINDOW_SECONDS = 600  # FR-02.12


@dataclass(frozen=True)
class TransactionFilters:
    """Already-normalized filters (UTC instants, resolved category ids). See FR-02.02."""

    start: dt.datetime | None = None  # inclusive
    end: dt.datetime | None = None  # exclusive
    transaction_type: str | None = None
    category_ids: Sequence[uuid.UUID] = field(default_factory=tuple)
    payment_methods: Sequence[str] = field(default_factory=tuple)
    q: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    category_status: str | None = None
    possible_duplicate: bool | None = None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class TransactionRepository(ScopedRepository[Transaction]):
    model = Transaction

    @staticmethod
    def _conditions(user_id: uuid.UUID, f: TransactionFilters) -> list[ColumnElement[bool]]:
        t = Transaction
        conds: list[ColumnElement[bool]] = [t.user_id == user_id]
        if f.start is not None:
            conds.append(t.transaction_date >= f.start)
        if f.end is not None:
            conds.append(t.transaction_date < f.end)
        if f.transaction_type:
            conds.append(t.transaction_type == f.transaction_type)
        if f.category_ids:
            conds.append(t.category_id.in_(list(f.category_ids)))
        if f.payment_methods:
            conds.append(t.payment_method.in_(list(f.payment_methods)))
        if f.q:
            pattern = f"%{_escape_like(f.q)}%"
            conds.append(
                or_(
                    t.description.ilike(pattern, escape="\\"),
                    t.merchant.ilike(pattern, escape="\\"),
                )
            )
        if f.min_amount is not None:
            conds.append(t.amount >= f.min_amount)
        if f.max_amount is not None:
            conds.append(t.amount <= f.max_amount)
        if f.category_status:
            conds.append(t.category_status == f.category_status)
        if f.possible_duplicate:
            conds.append(t.possible_duplicate_of.is_not(None))
        return conds

    def search(
        self,
        user_id: uuid.UUID,
        filters: TransactionFilters,
        *,
        sort: str,
        limit: int,
        after: Cursor | None = None,
    ) -> list[Transaction]:
        """Keyset page ordered by ``(sort key desc, id desc)``; returns up to ``limit`` rows."""
        t = Transaction
        stmt: Any = select(t).where(*self._conditions(user_id, filters))
        if sort == "amount":
            key_col: Any = t.amount
            if after is not None:
                stmt = stmt.where(
                    or_(
                        t.amount < Decimal(after.key),
                        and_(t.amount == Decimal(after.key), t.id < after.id),
                    )
                )
        else:
            key_col = t.transaction_date
            if after is not None:
                cutoff = dt.datetime.fromisoformat(after.key)
                stmt = stmt.where(
                    or_(
                        t.transaction_date < cutoff,
                        and_(t.transaction_date == cutoff, t.id < after.id),
                    )
                )
        stmt = stmt.order_by(key_col.desc(), t.id.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def count_matching(self, user_id: uuid.UUID, filters: TransactionFilters) -> int:
        stmt = (
            select(func.count()).select_from(Transaction).where(*self._conditions(user_id, filters))
        )
        return int(self.session.execute(stmt).scalar_one())

    def get_for_update(self, user_id: uuid.UUID, id: uuid.UUID) -> Transaction | None:
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.id == id)
            .with_for_update()
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_many(self, user_id: uuid.UUID, ids: Sequence[uuid.UUID]) -> list[Transaction]:
        stmt = (
            select(Transaction)
            .where(Transaction.user_id == user_id, Transaction.id.in_(list(ids)))
            .order_by(Transaction.id)
            .with_for_update()
        )
        return list(self.session.execute(stmt).scalars())

    def find_duplicate(
        self,
        user_id: uuid.UUID,
        *,
        transaction_type: str,
        amount: Decimal,
        merchant_key: str,
        occurred_at: dt.datetime,
        has_time: bool,
        timezone: str,
        exclude_id: uuid.UUID | None = None,
    ) -> Transaction | None:
        """Oldest transaction that FR-02.12 calls a duplicate of the given values, if any."""
        t = Transaction
        local_date = occurred_at.astimezone(dt.UTC).astimezone(_zone(timezone)).date()
        close_in_time = func.abs(func.extract("epoch", t.transaction_date - occurred_at)) <= (
            DUPLICATE_WINDOW_SECONDS
        )
        same_local_day = func.date(func.timezone(timezone, t.transaction_date)) == local_date
        if has_time:
            # Both timed: within 10 minutes. Existing row without a time: same local day.
            time_rule = or_(
                and_(t.has_time.is_(True), close_in_time),
                and_(t.has_time.is_(False), same_local_day),
            )
        else:
            time_rule = same_local_day
        stmt = (
            select(t)
            .where(
                t.user_id == user_id,
                t.transaction_type == transaction_type,
                t.amount == amount,
                t.merchant_key == merchant_key,
                time_rule,
            )
            .order_by(t.created_at, t.id)
            .limit(1)
        )
        if exclude_id is not None:
            stmt = stmt.where(t.id != exclude_id)
        return self.session.execute(stmt).scalar_one_or_none()

    def duplicate_candidates(
        self,
        user_id: uuid.UUID,
        keys: Collection[tuple[str, Decimal, str]],
        start: dt.datetime,
        end: dt.datetime,
    ) -> list[Any]:
        """Existing rows sharing ``(type, amount, merchant_key)`` with any key, oldest first.

        One query for a whole CSV (the caller applies the time rule of FR-02.12 in memory).
        """
        if not keys:
            return []
        t = Transaction
        stmt = (
            select(
                t.id, t.transaction_type, t.amount, t.merchant_key, t.transaction_date, t.has_time
            )
            .where(
                t.user_id == user_id,
                tuple_(t.transaction_type, t.amount, t.merchant_key).in_(list(keys)),
                t.transaction_date >= start,
                t.transaction_date < end,
            )
            .order_by(t.created_at, t.id)
        )
        return list(self.session.execute(stmt).all())

    def add_many(self, user_id: uuid.UUID, rows: Sequence[Transaction]) -> None:
        """Attach many new transactions to ``user_id`` with one flush (CSV commit)."""
        for row in rows:
            if row.user_id is not None and row.user_id != user_id:
                raise ValueError("entity already belongs to another user")
            row.user_id = user_id
        self.session.add_all(list(rows))
        self.session.flush()

    def delete_many(self, user_id: uuid.UUID, ids: Sequence[uuid.UUID]) -> int:
        removed = 0
        for row in self.get_many(user_id, ids):
            self.session.delete(row)
            removed += 1
        self.session.flush()
        return removed

    def apply_category_to_merchant(
        self,
        user_id: uuid.UUID,
        merchant_key: str,
        category_id: uuid.UUID,
        transaction_types: Sequence[str],
        *,
        exclude_id: uuid.UUID,
    ) -> int:
        """Past rows of one merchant that the user has not locked (FR-03.08), as ``rule`` rows."""
        t = Transaction
        stmt = (
            update(t)
            .where(
                t.user_id == user_id,
                t.merchant_key == merchant_key,
                t.id != exclude_id,
                t.transaction_type.in_(list(transaction_types)),
                t.category_status.not_in(("user_set", "user_confirmed")),
                t.category_id != category_id,
            )
            .values(
                category_id=category_id,
                category_status="rule",
                version=t.version + 1,
                updated_at=func.now(),
            )
        )
        return int(self.session.execute(stmt).rowcount)  # type: ignore[attr-defined]

    def set_category_many(
        self, user_id: uuid.UUID, ids: Sequence[uuid.UUID], category_id: uuid.UUID, status: str
    ) -> int:
        stmt = (
            update(Transaction)
            .where(Transaction.user_id == user_id, Transaction.id.in_(list(ids)))
            .values(
                category_id=category_id,
                category_status=status,
                version=Transaction.version + 1,
                updated_at=func.now(),
            )
        )
        result = self.session.execute(stmt)
        return int(result.rowcount)  # type: ignore[attr-defined]


def _zone(name: str) -> dt.tzinfo:
    from zoneinfo import ZoneInfo

    return ZoneInfo(name)
