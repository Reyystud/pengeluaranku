"""The jobs the backend runs (PRD 15.1). Each is idempotent for the same date.

Not here, on purpose: ``export-bigquery``, ``feedback-export``, ``purge-deleted-users``,
``training-weekly``, ``drift-report`` and ``clustering-weekly`` run in the pipelines image,
``shadow-evaluate`` arrives with T-39, and ``demo-reset`` is the demo seeder (``make seed-demo``).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, delete, exists, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.jobs.framework import JobContext, JobSpec
from app.models import (
    AnomalySuppression,
    Budget,
    Forecast,
    ForecastOutcome,
    IdempotencyKey,
    Notification,
    OutboxEvent,
    ProcessedEvent,
    Transaction,
    TransactionImport,
    User,
)
from app.models.base import utcnow
from app.repositories.analytics import AnalyticsRepository, bounds_to_utc
from app.repositories.notifications import NotificationRepository
from app.repositories.transactions import TransactionRepository
from app.services.anomalies import AnomalyService
from app.services.budgets import BudgetService
from app.services.categorization import MlCategorizer
from app.services.forecasts import ForecastService
from app.services.insight_rules import idr
from app.services.insights import LIVE_RECURRING, InsightService
from app.services.recurring import RecurringService
from app.services.transactions import TransactionService

_DAY = dt.timedelta(days=1)


# -- who is eligible -----------------------------------------------------------------------------
def _has_transactions(_: JobContext) -> ColumnElement[bool]:
    return exists().where(Transaction.user_id == User.id)


def _active(ctx: JobContext) -> ColumnElement[bool]:
    since = ctx.now - dt.timedelta(days=ctx.cfg.active_days)
    return exists().where(Transaction.user_id == User.id, Transaction.transaction_date >= since)


def _has_budgets(_: JobContext) -> ColumnElement[bool]:
    return exists().where(Budget.user_id == User.id)


# -- per-user jobs -------------------------------------------------------------------------------
def daily_budget_close(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    """Snapshots and forecast outcomes of the period that just closed (FR-05.08, 7.7).

    Written for the period before the current one, so the first run after a period ends does the
    work and every later run (or a retry after a failed day) finds it already there.
    """
    budgets = BudgetService(session, user, ctx.now)
    closed = budgets.analytics.period_of(budgets.current_period().start - _DAY)
    snapshots = budgets.snapshot_closed_period()
    return {"snapshots": snapshots, "outcomes": _forecast_outcomes(session, user, closed)}


def _forecast_outcomes(session: Session, user: User, closed: object) -> int:
    """Compare what was forecast during the closed period with what was spent (PRD 12.2)."""
    tz = ZoneInfo(user.timezone)
    start, end = closed.start, closed.end  # type: ignore[attr-defined]
    rows = list(
        session.execute(
            select(Forecast)
            .where(Forecast.user_id == user.id, Forecast.period_id == start)
            .order_by(Forecast.as_of)
        ).scalars()
    )
    if not rows:
        return 0
    lo, hi = bounds_to_utc(start, end, tz)
    analytics = AnalyticsRepository(session)
    overall = analytics.flows_between(user.id, lo, hi).expenses
    by_category = {r.slug: r.amount for r in analytics.category_breakdown(user.id, lo, hi)}
    slug_of = {
        cid: slug for cid, slug in session.execute(text("SELECT id, slug FROM categories")).all()
    }
    latest: dict[tuple[object, int], Forecast] = {}
    for row in rows:  # ordered by as_of: the last forecast of a day wins
        day = (row.as_of.astimezone(tz).date() - start).days + 1
        latest[(row.category_id, day)] = row
    written = 0
    for (category_id, day), row in latest.items():
        actual = (
            overall if category_id is None else by_category.get(slug_of[category_id], Decimal(0))
        )
        stmt = (
            insert(ForecastOutcome)
            .values(
                user_id=user.id,
                period_id=start,
                category_id=category_id,
                forecast_day=day,
                predicted_total=row.predicted_total,
                baseline_prediction=row.baseline_prediction,
                actual_total=Decimal(actual),
                model_version=row.model_version,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing()
            .returning(ForecastOutcome.id)
        )
        written += 1 if session.execute(stmt).first() is not None else 0
    return written


def daily_forecast(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    return {"forecasts": ForecastService(session, user, ctx.now).refresh_all()}


def category_surge(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    return {"surges": AnomalyService(session, user, ctx.now).detect_category_surges()}


def recurring_refresh(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    return {"series": RecurringService(session, user, ctx.now).detect()}


def daily_insights(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    out = InsightService(session, user, ctx.now).refresh()
    return {"created": out.created, "removed": out.removed, "total": out.total}


def recurring_due_soon(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    """Notify about payments due within the configured days (FR-14)."""
    recurring = RecurringService(session, user, ctx.now)
    today = recurring.today
    horizon = today + dt.timedelta(days=ctx.cfg.recurring_due_soon_days)
    notifications = NotificationRepository(session)
    created = 0
    for s in recurring.repo.all(user.id):
        if s.transaction_type != "expense" or recurring.live_status(s) not in LIVE_RECURRING:
            continue
        if not today <= s.next_expected_date <= horizon:
            continue
        amount = recurring.effective_amount(s)
        created += notifications.create_once(
            user.id,
            type="recurring_due_soon",
            title=f"{s.merchant_display} is due {s.next_expected_date.isoformat()}",
            body=f"{s.merchant_display} is expected around {s.next_expected_date.isoformat()}, "
            f"about {idr(amount)}.",
            link="/recurring",
            payload={
                "series_id": str(s.id),
                "merchant_key": s.merchant_key,
                "next_expected_date": s.next_expected_date.isoformat(),
                "amount": f"{amount:.2f}",
            },
            dedupe_key=f"recurring-due:{s.id}:{s.next_expected_date.isoformat()}",
        )
    return {"notifications": created}


def review_queue_reminder(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    count = AnalyticsRepository(session).review_queue_count(user.id)
    if count < ctx.cfg.review_queue_min:
        return {"notifications": 0}
    today = ctx.now.astimezone(ZoneInfo(user.timezone)).date()
    iso = today.isocalendar()
    created = NotificationRepository(session).create_once(
        user.id,
        type="review_queue",
        title=f"{count} transactions need a category",
        body="Reviewing them improves your insights and forecasts.",
        link="/transactions?category_status=needs_review",
        payload={"count": count},
        dedupe_key=f"review-queue:{iso.year}-W{iso.week:02d}",
    )
    return {"notifications": int(created)}


def recategorize_needs_review(session: Session, user: User, ctx: JobContext) -> dict[str, int]:
    """Re-run rule and model for transactions saved while the ML service was unavailable."""
    if ctx.ml is None:
        raise RuntimeError("this job needs the ML client")
    ids = TransactionRepository(session).needs_review_ids(user.id, ctx.cfg.recategorize_batch)
    if not ids:
        return {"recategorized": 0, "still_needs_review": 0}
    service = TransactionService(session, ctx.settings, user)
    service.categorizer = MlCategorizer(session, ctx.ml, service.by_slug, service.by_id)
    done = still = 0
    for tx_id in ids:
        result = service.recategorize(tx_id, force=False)
        if result.categorization.decision == "needs_review":
            still += 1
        else:
            done += 1
    return {"recategorized": done, "still_needs_review": still}


# -- global jobs ---------------------------------------------------------------------------------
def cleanup(session: Session, ctx: JobContext) -> dict[str, int]:
    """Retention (PRD 12.3): expire staged imports, prune what has outlived its purpose."""
    now = ctx.now
    keep = ctx.cfg.retention_days

    def ago(key: str) -> dt.datetime:
        return now - dt.timedelta(days=keep[key])

    def rows(result: object) -> int:
        return int(result.rowcount)  # type: ignore[attr-defined]

    expired = session.execute(
        update(TransactionImport)
        .where(TransactionImport.status == "previewed", TransactionImport.expires_at < now)
        .values(status="expired", staged_rows=[])
    )
    return {
        "imports_expired": rows(expired),
        "idempotency_keys": rows(
            session.execute(
                delete(IdempotencyKey).where(IdempotencyKey.created_at < ago("idempotency_keys"))
            )
        ),
        "processed_events": rows(
            session.execute(
                delete(ProcessedEvent).where(ProcessedEvent.processed_at < ago("processed_events"))
            )
        ),
        "outbox_events": rows(
            session.execute(
                delete(OutboxEvent).where(
                    OutboxEvent.published_at.is_not(None),
                    OutboxEvent.published_at < ago("outbox_published"),
                )
            )
        ),
        "notifications": rows(
            session.execute(
                delete(Notification).where(Notification.created_at < ago("notifications"))
            )
        ),
        "forecast_outcomes": rows(
            session.execute(
                delete(ForecastOutcome).where(ForecastOutcome.created_at < ago("forecast_outcomes"))
            )
        ),
        "anomaly_suppressions": rows(
            session.execute(delete(AnomalySuppression).where(AnomalySuppression.expires_at < now))
        ),
    }


JOBS: dict[str, JobSpec] = {
    spec.name: spec
    for spec in (
        JobSpec(
            "daily-budget-close",
            "Budget snapshots and forecast outcomes of the closed period",
            user_fn=daily_budget_close,
            eligible=_has_budgets,
        ),
        JobSpec(
            "daily-forecast",
            "Recompute overall and category forecasts",
            user_fn=daily_forecast,
            eligible=_active,
        ),
        JobSpec(
            "category-surge",
            "Category surge anomaly rule",
            user_fn=category_surge,
            eligible=_active,
        ),
        JobSpec(
            "recurring-refresh",
            "Recompute recurring series",
            user_fn=recurring_refresh,
            eligible=_has_transactions,
        ),
        JobSpec(
            "daily-insights",
            "Regenerate insights",
            user_fn=daily_insights,
            eligible=_has_transactions,
        ),
        JobSpec(
            "recurring-due-soon",
            "Notify about payments due soon",
            user_fn=recurring_due_soon,
            eligible=_has_transactions,
        ),
        JobSpec(
            "review-queue-reminder",
            "Weekly review queue reminder",
            user_fn=review_queue_reminder,
            eligible=_has_transactions,
        ),
        JobSpec(
            "recategorize-needs-review",
            "Re-run categorization for needs_review rows",
            user_fn=recategorize_needs_review,
            eligible=_has_transactions,
        ),
        JobSpec("cleanup", "Expire imports and prune old rows", global_fn=cleanup),
    )
}
