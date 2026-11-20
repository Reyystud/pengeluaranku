"""Anomalies, their history features and merchant suppressions (PRD 7.6, 11.2.2, 12.2).

Every method takes ``user_id`` first and filters on it. History queries use only rows strictly
before the scored transaction in the order ``(transaction_date, created_at, id)``, so re-scoring an
old transaction later gives the same answer as scoring it on the day (PRD 11.1 rule 2).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Anomaly, AnomalySuppression, Transaction
from app.models.base import utcnow
from app.repositories.base import ScopedRepository
from ml.anomaly_detection import UserHistory
from ml.anomaly_detection.baseline import p95

DAY = dt.timedelta(days=1)


class AnomalyRepository(ScopedRepository[Anomaly]):
    model = Anomaly

    # -- reads -------------------------------------------------------------------------------
    def page(
        self,
        user_id: uuid.UUID,
        *,
        statuses: Sequence[str],
        severity: str | None,
        anomaly_type: str | None,
        period_id: dt.date | None,
        alerts_only: bool,
        limit: int,
        after: tuple[dt.datetime, uuid.UUID] | None,
    ) -> list[tuple[Anomaly, Transaction | None]]:
        """Newest first, with the scored transaction (None for a category surge)."""
        stmt = (
            select(Anomaly, Transaction)
            .outerjoin(
                Transaction,
                and_(Transaction.id == Anomaly.transaction_id, Transaction.user_id == user_id),
            )
            .where(Anomaly.user_id == user_id, Anomaly.status.in_(statuses))
        )
        if severity:
            stmt = stmt.where(Anomaly.severity == severity)
        if anomaly_type:
            stmt = stmt.where(Anomaly.anomaly_type == anomaly_type)
        if period_id:
            stmt = stmt.where(Anomaly.period_id == period_id)
        if alerts_only:
            stmt = stmt.where(Anomaly.is_alert.is_(True))
        if after is not None:
            created, last_id = after
            stmt = stmt.where(
                or_(
                    Anomaly.created_at < created,
                    and_(Anomaly.created_at == created, Anomaly.id < last_id),
                )
            )
        stmt = stmt.order_by(Anomaly.created_at.desc(), Anomaly.id.desc()).limit(limit)
        return [(a, t) for a, t in self.session.execute(stmt)]

    def get_with_transaction(
        self, user_id: uuid.UUID, anomaly_id: uuid.UUID
    ) -> tuple[Anomaly, Transaction | None] | None:
        stmt = (
            select(Anomaly, Transaction)
            .outerjoin(
                Transaction,
                and_(Transaction.id == Anomaly.transaction_id, Transaction.user_id == user_id),
            )
            .where(Anomaly.user_id == user_id, Anomaly.id == anomaly_id)
        )
        row = self.session.execute(stmt).first()
        return None if row is None else (row[0], row[1])

    def alerts_in_period(self, user_id: uuid.UUID, period_id: dt.date) -> int:
        stmt = (
            select(func.count())
            .select_from(Anomaly)
            .where(
                Anomaly.user_id == user_id,
                Anomaly.period_id == period_id,
                Anomaly.is_alert.is_(True),
                Anomaly.status.in_(("open", "confirmed")),
            )
        )
        return int(self.session.execute(stmt).scalar_one())

    def has_open_surge(self, user_id: uuid.UUID, category_id: uuid.UUID) -> bool:
        stmt = select(Anomaly.id).where(
            Anomaly.user_id == user_id,
            Anomaly.category_id == category_id,
            Anomaly.anomaly_type == "category_surge",
            Anomaly.status == "open",
        )
        return self.session.execute(stmt).first() is not None

    # -- writes ------------------------------------------------------------------------------
    def supersede_for_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> int:
        """FR-06.07: a re-score replaces the unreviewed rows; feedback rows are kept."""
        stmt = (
            update(Anomaly)
            .where(
                Anomaly.user_id == user_id,
                Anomaly.transaction_id == transaction_id,
                Anomaly.status.in_(("open", "historical")),
            )
            .values(status="superseded", is_alert=False, updated_at=utcnow())
        )
        return int(self.session.execute(stmt).rowcount)  # type: ignore[attr-defined]

    def insert_once(self, user_id: uuid.UUID, values: dict[str, Any]) -> bool:
        """Insert unless the partial unique indexes already hold an equivalent row."""
        stmt = (
            insert(Anomaly)
            .values(user_id=user_id, **values)
            .on_conflict_do_nothing()
            .returning(Anomaly.id)
        )
        return self.session.execute(stmt).first() is not None

    # -- history features (PRD 11.2.2) -------------------------------------------------------
    def history_for(
        self,
        user_id: uuid.UUID,
        tx: Transaction,
        *,
        history_days: int,
        rate_days: int,
    ) -> UserHistory:
        """Features of 11.2.2 for ``tx`` from rows strictly before it, in SQL."""
        t = Transaction
        before = tuple_(t.transaction_date, t.created_at, t.id) < tuple_(
            tx.transaction_date, tx.created_at, tx.id
        )
        base = (t.user_id == user_id, before)
        window_lo = tx.transaction_date - history_days * DAY

        cat_amounts = (
            self.session.execute(
                select(t.amount).where(
                    *base,
                    t.transaction_type == "expense",
                    t.category_id == tx.category_id,
                    t.transaction_date >= window_lo,
                )
            )
            .scalars()
            .all()
        )
        merchant_seen = False
        merchant_amounts: list[Decimal] = []
        if tx.merchant_key:
            merchant_seen = (
                self.session.execute(
                    select(t.id).where(*base, t.merchant_key == tx.merchant_key).limit(1)
                ).first()
                is not None
            )
            merchant_amounts = list(
                self.session.execute(
                    select(t.amount).where(
                        *base,
                        t.transaction_type == "expense",
                        t.merchant_key == tx.merchant_key,
                        t.transaction_date >= window_lo,
                    )
                )
                .scalars()
                .all()
            )
        expense_recent = (
            self.session.execute(
                select(t.amount).where(
                    *base, t.transaction_type == "expense", t.transaction_date >= window_lo
                )
            )
            .scalars()
            .all()
        )
        expense_count = int(
            self.session.execute(
                select(func.count()).where(*base, t.transaction_type == "expense")
            ).scalar_one()
        )
        in_cat = (*base, t.transaction_type == "expense", t.category_id == tx.category_id)
        count_24h, count_rate = self.session.execute(
            select(
                func.count().filter(t.transaction_date > tx.transaction_date - DAY),
                func.count().filter(t.transaction_date >= tx.transaction_date - rate_days * DAY),
            ).where(*in_cat)
        ).one()
        first = self.session.execute(select(func.min(t.transaction_date)).where(*base)).scalar_one()
        return UserHistory(
            category_amounts=tuple(float(a) for a in cat_amounts),
            merchant_amounts=tuple(float(a) for a in merchant_amounts),
            merchant_seen=merchant_seen,
            expense_p95=p95([float(a) for a in expense_recent]),
            expense_count=expense_count,
            category_count_24h=int(count_24h),
            category_count_rate_window=int(count_rate),
            history_days=0.0 if first is None else (tx.transaction_date - first) / DAY,
        )

    def weekly_category_spend(
        self,
        user_id: uuid.UUID,
        tz_name: str,
        today: dt.date,
        window_days: int,
        weeks: int,
    ) -> dict[uuid.UUID, list[float]]:
        """Per category: spend in the last window (index 0) and the ``weeks`` windows before it.

        Windows are ``window_days`` long and end on ``today`` (local date), so index 0 is the last
        7 days and indexes 1..weeks are the baseline weeks, oldest last.
        """
        rows = self.session.execute(
            text(
                """
                SELECT category_id,
                       ((CAST(:today AS date) - (transaction_date AT TIME ZONE :tz)::date)
                         / :w) AS bucket,
                       SUM(amount) AS spend
                FROM transactions
                WHERE user_id = :user_id
                  AND transaction_type = 'expense'
                  AND (transaction_date AT TIME ZONE :tz)::date <= CAST(:today AS date)
                  AND (transaction_date AT TIME ZONE :tz)::date
                      > CAST(:today AS date) - :span
                GROUP BY category_id, bucket
                """
            ),
            {
                "user_id": user_id,
                "tz": tz_name,
                "today": today,
                "w": window_days,
                "span": window_days * (weeks + 1),
            },
        )
        out: dict[uuid.UUID, list[float]] = {}
        for category_id, bucket, spend in rows:
            series = out.setdefault(category_id, [0.0] * (weeks + 1))
            series[int(bucket)] = float(spend)
        return out

    def category_expense_count(self, user_id: uuid.UUID, category_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "expense",
                Transaction.category_id == category_id,
            )
        )
        return int(self.session.execute(stmt).scalar_one())


class AnomalySuppressionRepository:
    """Keyed by ``(user_id, merchant_key)`` (FR-06.05)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def is_suppressed(self, user_id: uuid.UUID, merchant_key: str, now: dt.datetime) -> bool:
        if not merchant_key:
            return False
        stmt = select(AnomalySuppression.merchant_key).where(
            AnomalySuppression.user_id == user_id,
            AnomalySuppression.merchant_key == merchant_key,
            AnomalySuppression.expires_at > now,
        )
        return self.session.execute(stmt).first() is not None

    def suppress(self, user_id: uuid.UUID, merchant_key: str, expires_at: dt.datetime) -> None:
        stmt = (
            insert(AnomalySuppression)
            .values(user_id=user_id, merchant_key=merchant_key, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=["user_id", "merchant_key"], set_={"expires_at": expires_at}
            )
        )
        self.session.execute(stmt)
