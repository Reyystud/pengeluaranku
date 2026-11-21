"""In-process event path (PRD 6.3, 7.11): drain this user's pending outbox events.

Two consumers read each event: the anomaly scorer and the recurring updater (FR-08.06).

The outbox rows are written in the same transaction as the change. Running the consumer right after
the write (same transaction, inside a savepoint) keeps the baseline detector free of any network
hop and makes saving a transaction independent of it: a failure rolls back only the savepoint, the
event stays pending and is retried on the next write. ``processed_events`` makes handling
idempotent per ``(event_id, consumer)`` (PRD 14.3).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import OutboxEvent, ProcessedEvent, User
from app.models.base import utcnow
from app.services.anomalies import AnomalyService
from app.services.recurring import RecurringService

log = logging.getLogger(__name__)
CONSUMER = "anomaly-scorer"
RECURRING_CONSUMER = "recurring-updater"
SCORED_EVENTS = ("transaction.created", "transaction.updated")


def drain_pending(session: Session, user: User, limit: int) -> int:
    """Handle up to ``limit`` pending events of ``user``; returns how many were handled."""
    events = list(
        session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.user_id == user.id, OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    if not events:
        return 0
    service = AnomalyService(session, user)
    touched: set[uuid.UUID] = set()
    for event in events:
        if _claim(session, event, CONSUMER) and event.event_type in SCORED_EVENTS:
            service.score_transaction(uuid.UUID(event.payload["data"]["transaction_id"]))
        if _claim(session, event, RECURRING_CONSUMER) and event.event_type in SCORED_EVENTS:
            touched.add(uuid.UUID(event.payload["data"]["transaction_id"]))
        event.published_at = utcnow()
    if touched:  # FR-08.06: one refresh per known recurring merchant, however many rows arrived
        RecurringService(session, user).refresh_for_transactions(touched)
    return len(events)


def _claim(session: Session, event: OutboxEvent, consumer: str) -> bool:
    """True the first time ``consumer`` sees ``event`` (idempotent handling, PRD 14.3)."""
    claimed = session.execute(
        insert(ProcessedEvent)
        .values(event_id=event.id, consumer=consumer, processed_at=utcnow())
        .on_conflict_do_nothing()
        .returning(ProcessedEvent.event_id)
    ).first()
    return claimed is not None


def drain_safely(session: Session, user: User, limit: int) -> None:
    """Never let anomaly scoring fail the write that triggered it (PRD 6.3)."""
    try:
        with session.begin_nested():
            drain_pending(session, user, limit)
    except Exception:
        log.warning("anomaly event drain failed; events stay pending", exc_info=False)
