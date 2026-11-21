"""Anomaly detection service (PRD 6.3, 7.6): scoring, alert budget, suppressions, feedback.

Scoring runs in-process from the outbox events of the same request (``events/dispatcher.py``), so
saving a transaction never depends on a network call. The detector is the baseline of
``ml.anomaly_detection``; its thresholds come from ``config/anomaly.yaml``. Nothing here logs
amounts, merchants or descriptions (PRD 17.3).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import ProblemError, not_found
from app.core.ids import new_uuid7
from app.core.metrics import ANOMALIES
from app.models import Anomaly, Transaction, User
from app.models.base import utcnow
from app.repositories import (
    AnomalyRepository,
    AnomalySuppressionRepository,
    CategoryRepository,
    NotificationRepository,
    TransactionRepository,
)
from app.schemas.anomalies import (
    AnomalyFeedback,
    AnomalyOut,
    AnomalyPage,
    AnomalyTransaction,
    ReasonOut,
)
from app.schemas.transactions import CategoryRef
from app.services.analytics import AnalyticsService
from ml.anomaly_detection import (
    CategoryPrior,
    Detection,
    UserHistory,
    detect,
    detect_surge,
    load_anomaly_config,
)
from ml.anomaly_detection import Transaction as ScoredTransaction
from ml.anomaly_detection.config import load_category_priors

ALERT_SEVERITIES = ("medium", "high")
SORT = "created"
DEFAULT_STATUSES = ("open", "confirmed", "dismissed", "historical")
_ORDER = {"high": 2, "medium": 1, "low": 0}


class AnomalyService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.cfg = load_anomaly_config()
        self.repo = AnomalyRepository(session)
        self.suppressions = AnomalySuppressionRepository(session)
        self.notifications = NotificationRepository(session)
        self.transactions = TransactionRepository(session)
        self.analytics = AnalyticsService(session, user, now)
        self.now = self.analytics.now
        self.tz = ZoneInfo(user.timezone)
        cats = CategoryRepository(session).list()
        self.by_id = {c.id: c for c in cats}

    # -- scoring (FR-06.01 .. FR-06.07) --------------------------------------------------------
    def score_transaction(self, transaction_id: uuid.UUID) -> int:
        """(Re)score one transaction; returns how many anomaly rows were created."""
        tx = self.transactions.get(self.user.id, transaction_id)
        if tx is None:  # deleted again before the event ran: the cascade already removed its rows
            return 0
        self.repo.supersede_for_transaction(self.user.id, tx.id)  # FR-06.07
        if tx.transaction_type != "expense":
            return 0
        category = self.by_id[tx.category_id]
        history = self.repo.history_for(
            self.user.id,
            tx,
            history_days=self.cfg.history_days,
            rate_days=self.cfg.burst_rate_days,
        )
        prior = load_category_priors().get(category.slug)
        history = _with_prior(history, CategoryPrior(*prior) if prior else None)
        shown = tx.merchant or tx.description
        found = detect(
            ScoredTransaction(tx.amount, category.name, tx.merchant_key, shown[:80]),
            history,
            self.cfg,
        )
        found.sort(key=lambda d: (-_ORDER[d.severity], -d.score))
        local_day = tx.transaction_date.astimezone(self.tz).date()
        period_id = self.analytics.period_of(local_day).start
        historical = self.now - tx.transaction_date > dt.timedelta(days=self.cfg.alert_max_age_days)
        suppressed = self.suppressions.is_suppressed(self.user.id, tx.merchant_key, self.now)
        established = history.history_days >= self.cfg.min_history_days
        used = self.repo.alerts_in_period(self.user.id, period_id)
        created = 0
        for d in found:
            wants_alert = (
                not historical
                and not suppressed
                and established
                and d.anomaly_type != "amount_low"
                and d.severity in ALERT_SEVERITIES
            )
            is_alert = wants_alert and used < self.cfg.alerts_per_period
            anomaly_id = new_uuid7()
            inserted = self.repo.insert_once(
                self.user.id,
                self._values(
                    anomaly_id,
                    d,
                    transaction_id=tx.id,
                    category_id=tx.category_id,
                    period_id=period_id,
                    status="historical" if historical else "open",
                    is_alert=is_alert,
                    version=tx.version,
                ),
            )
            if not inserted:
                continue
            created += 1
            ANOMALIES.labels(d.anomaly_type, d.severity, str(is_alert).lower()).inc()
            if is_alert:
                used += 1
                self._notify(anomaly_id, d, category.name, tx.id)
        return created

    def _values(
        self,
        anomaly_id: uuid.UUID,
        d: Detection,
        *,
        transaction_id: uuid.UUID | None,
        category_id: uuid.UUID | None,
        period_id: dt.date,
        status: str,
        is_alert: bool,
        version: int | None,
    ) -> dict[str, object]:
        now = utcnow()
        return {
            "id": anomaly_id,
            "transaction_id": transaction_id,
            "category_id": category_id,
            "anomaly_type": d.anomaly_type,
            "anomaly_score": Decimal(f"{d.score:.4f}"),
            "severity": d.severity,
            "is_alert": is_alert,
            "status": status,
            "history_level": d.history_level,
            "reasons": [
                {
                    "code": r.code,
                    "feature": r.feature,
                    "value": r.value,
                    "reference": r.reference,
                    "message": r.message,
                }
                for r in d.reasons
            ],
            "model_version": self.cfg.version,
            "feature_version": self.cfg.feature_version,
            "period_id": period_id,
            "transaction_version": version,
            "created_at": now,
            "updated_at": now,
        }

    def _notify(
        self, anomaly_id: uuid.UUID, d: Detection, category: str, tx_id: uuid.UUID | None
    ) -> None:
        self.notifications.create_once(
            self.user.id,
            type="anomaly_alert",
            title=f"Unusual {category} spending",
            body=d.reasons[0].message,
            link="/intelligence",
            payload={
                "anomaly_id": str(anomaly_id),
                "anomaly_type": d.anomaly_type,
                "severity": d.severity,
                "transaction_id": str(tx_id) if tx_id else None,
            },
            dedupe_key=f"anomaly:{anomaly_id}",
        )

    # -- pattern anomaly (daily job, T-37) -----------------------------------------------------
    def detect_category_surges(self) -> int:
        """Last 7 days against the previous 8 weeks, per category (PRD 7.6.2, 15.1)."""
        today = self.analytics.today
        weeks = self.cfg.surge_baseline_weeks
        series = self.repo.weekly_category_spend(
            self.user.id, self.user.timezone, today, self.cfg.surge_window_days, weeks
        )
        period_id = self.analytics.period_of(today).start
        used = self.repo.alerts_in_period(self.user.id, period_id)
        created = 0
        for category_id, spend in sorted(series.items(), key=lambda kv: str(kv[0])):
            category = self.by_id.get(category_id)
            if category is None or self.repo.has_open_surge(self.user.id, category_id):
                continue
            limited = (
                self.repo.category_expense_count(self.user.id, category_id)
                < self.cfg.min_category_history
            )
            d = detect_surge(category.name, spend[0], spend[1:], self.cfg, limited=limited)
            if d is None:
                continue
            is_alert = used < self.cfg.alerts_per_period
            anomaly_id = new_uuid7()
            if self.repo.insert_once(
                self.user.id,
                self._values(
                    anomaly_id,
                    d,
                    transaction_id=None,
                    category_id=category_id,
                    period_id=period_id,
                    status="open",
                    is_alert=is_alert,
                    version=None,
                ),
            ):
                created += 1
                if is_alert:
                    used += 1
                    self._notify(anomaly_id, d, category.name, None)
        return created

    # -- read ----------------------------------------------------------------------------------
    def _out(self, a: Anomaly, tx: Transaction | None) -> AnomalyOut:
        category = self.by_id.get(a.category_id) if a.category_id else None
        return AnomalyOut(
            id=a.id,
            anomaly_type=a.anomaly_type,  # type: ignore[arg-type]
            severity=a.severity,  # type: ignore[arg-type]
            status=a.status,  # type: ignore[arg-type]
            is_alert=a.is_alert,
            score=float(a.anomaly_score),
            history_level=a.history_level,  # type: ignore[arg-type]
            category=CategoryRef(id=category.id, slug=category.slug, name=category.name)
            if category
            else None,
            period_id=a.period_id,
            reasons=[ReasonOut(**r) for r in a.reasons],
            transaction=AnomalyTransaction(
                id=tx.id,
                transaction_date=tx.transaction_date,
                amount=f"{tx.amount:.2f}",
                merchant=tx.merchant,
                description=tx.description,
            )
            if tx
            else None,
            model_version=a.model_version,
            feedback_reason=a.feedback_reason,  # type: ignore[arg-type]
            feedback_at=a.feedback_at,
            created_at=a.created_at,
        )

    def page(
        self,
        *,
        statuses: list[str] | None,
        severity: str | None,
        anomaly_type: str | None,
        period_id: dt.date | None,
        alerts_only: bool,
        limit: int,
        cursor: str | None,
        secret: str,
    ) -> AnomalyPage:
        after = None
        if cursor:
            c = decode_cursor(cursor, self.user.id, secret, SORT)
            after = (dt.datetime.fromisoformat(c.key), c.id)
        rows = self.repo.page(
            self.user.id,
            statuses=statuses or DEFAULT_STATUSES,
            severity=severity,
            anomaly_type=anomaly_type,
            period_id=period_id,
            alerts_only=alerts_only,
            limit=limit + 1,
            after=after,
        )
        page, more = rows[:limit], len(rows) > limit
        next_cursor = None
        if more and page:
            last = page[-1][0]
            next_cursor = encode_cursor(
                Cursor(sort=SORT, key=last.created_at.isoformat(), id=last.id),
                self.user.id,
                secret,
            )
        return AnomalyPage(items=[self._out(a, t) for a, t in page], next_cursor=next_cursor)

    def get(self, anomaly_id: uuid.UUID) -> AnomalyOut:
        row = self.repo.get_with_transaction(self.user.id, anomaly_id)
        if row is None:
            raise not_found()
        return self._out(*row)

    # -- feedback (FR-06.04, FR-06.05) ---------------------------------------------------------
    def feedback(self, anomaly_id: uuid.UUID, body: AnomalyFeedback) -> AnomalyOut:
        row = self.repo.get_with_transaction(self.user.id, anomaly_id)
        if row is None:
            raise not_found()
        anomaly, tx = row
        if anomaly.status == "superseded":
            raise ProblemError(
                409,
                "ANOMALY_SUPERSEDED",
                "Anomaly replaced",
                "This anomaly was replaced by a newer score. Reload the list.",
            )
        if body.action == "confirm":
            if body.reason is not None:
                raise ProblemError(
                    422, "INVALID_VALUE", "Invalid feedback", "A reason applies to dismiss only."
                )
            anomaly.status, anomaly.feedback_reason = "confirmed", None
        else:
            anomaly.status, anomaly.feedback_reason = "dismissed", body.reason
        anomaly.feedback_at = utcnow()
        anomaly.is_alert = anomaly.is_alert and anomaly.status == "confirmed"
        anomaly.updated_at = utcnow()
        if body.reason == "expected_purchase" and tx is not None and tx.merchant_key:
            self.suppressions.suppress(
                self.user.id,
                tx.merchant_key,
                utcnow() + dt.timedelta(days=self.cfg.suppression_days),
            )
        self.session.flush()
        return self._out(anomaly, tx)


def _with_prior(h: UserHistory, prior: CategoryPrior | None) -> UserHistory:
    return UserHistory(
        category_amounts=h.category_amounts,
        merchant_amounts=h.merchant_amounts,
        merchant_seen=h.merchant_seen,
        expense_p95=h.expense_p95,
        expense_count=h.expense_count,
        category_count_24h=h.category_count_24h,
        category_count_rate_window=h.category_count_rate_window,
        history_days=h.history_days,
        prior=prior,
    )
