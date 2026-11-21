"""Event consumers (PRD 6.3, 7.11): the in-process drain and the shared ``dispatch``.

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
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.metrics import EVENTS_CONSUMED, EVENTS_PUBLISHED
from app.models import OutboxEvent, ProcessedEvent, User
from app.models.base import utcnow
from app.repositories import TransactionRepository
from app.services.anomalies import AnomalyService
from app.services.recurring import RecurringService

log = logging.getLogger(__name__)
CONSUMER = "anomaly-scorer"
RECURRING_CONSUMER = "recurring-updater"
SCORED_EVENTS = ("transaction.created", "transaction.updated")


def drain_pending(session: Session, user: User, limit: int) -> int:
    """Handle up to ``limit`` pending events of ``user``; returns how many were handled.

    Used when ``EVENT_BUS=inmemory``. With Pub/Sub the relay owns ``published_at``.
    """
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
    dispatch(session, user, [(e.id, e.payload) for e in events])
    for event in events:
        event.published_at = utcnow()
        EVENTS_PUBLISHED.labels(event.event_type, "ok").inc()
    return len(events)


def dispatch(
    session: Session, user: User, deliveries: Sequence[tuple[uuid.UUID, dict[str, Any]]]
) -> None:
    """Run every consumer for each ``(event_id, envelope)``: shared by the in-process path and
    the worker's push endpoint. Idempotent per ``(event_id, consumer)`` (FR-11.03); an event whose
    ``transaction_version`` is older than the stored one is ignored (FR-11.04: a newer event for
    the same transaction follows). Raises if a consumer fails, so the caller can roll back the
    claims and let the bus retry.
    """
    service = AnomalyService(session, user)
    transactions = TransactionRepository(session)
    touched: set[uuid.UUID] = set()
    for event_id, envelope in deliveries:
        scored = envelope["event_type"] in SCORED_EVENTS
        tx_id = uuid.UUID(envelope["data"]["transaction_id"]) if scored else None
        if tx_id is not None and _is_stale(transactions, user, tx_id, envelope):
            EVENTS_CONSUMED.labels(CONSUMER, "stale").inc()
            EVENTS_CONSUMED.labels(RECURRING_CONSUMER, "stale").inc()
            continue
        try:
            if _claim(session, event_id, CONSUMER):
                if tx_id is not None:
                    service.score_transaction(tx_id)
                EVENTS_CONSUMED.labels(CONSUMER, "processed").inc()
            else:
                EVENTS_CONSUMED.labels(CONSUMER, "duplicate").inc()
            if _claim(session, event_id, RECURRING_CONSUMER):
                if tx_id is not None:
                    touched.add(tx_id)
                EVENTS_CONSUMED.labels(RECURRING_CONSUMER, "processed").inc()
            else:
                EVENTS_CONSUMED.labels(RECURRING_CONSUMER, "duplicate").inc()
        except Exception:
            EVENTS_CONSUMED.labels(CONSUMER, "error").inc()
            raise
    if touched:  # FR-08.06: one refresh per known recurring merchant, however many rows arrived
        RecurringService(session, user).refresh_for_transactions(touched)


def _is_stale(
    transactions: TransactionRepository, user: User, tx_id: uuid.UUID, envelope: dict[str, Any]
) -> bool:
    current = transactions.get(user.id, tx_id)
    return current is not None and int(envelope["data"]["transaction_version"]) < current.version


def _claim(session: Session, event_id: uuid.UUID, consumer: str) -> bool:
    """True the first time ``consumer`` sees ``event_id`` (idempotent handling, PRD 14.3)."""
    claimed = session.execute(
        insert(ProcessedEvent)
        .values(event_id=event_id, consumer=consumer, processed_at=utcnow())
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
