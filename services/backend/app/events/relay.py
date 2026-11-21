"""Outbox relay (PRD 7.11 FR-11.01/02): publish pending events, then mark them published.

``publish_pending`` selects with ``FOR UPDATE SKIP LOCKED`` so several workers never publish the
same row twice at once; a crash between publishing and the commit means a re-publish, which the
consumers absorb (at-least-once delivery, idempotent consumers, FR-11.03).
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.events.publisher import EventPublisher
from app.models import OutboxEvent
from app.models.base import utcnow

log = logging.getLogger(__name__)
MAX_BACKOFF_S = 30.0


def publish_pending(session: Session, publisher: EventPublisher, limit: int) -> int:
    """Publish up to ``limit`` pending events; the caller commits. Raises if publishing fails."""
    rows = list(
        session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    if not rows:
        return 0
    publisher.publish([row.payload for row in rows])
    now = utcnow()
    for row in rows:
        row.published_at = now
    return len(rows)


class Relay:
    """Background thread: poll, publish, repeat. Failures only delay events (they stay pending)."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        publisher: EventPublisher,
        *,
        interval_s: float = 1.0,
        batch_size: int = 100,
    ) -> None:
        self._factory = factory
        self._publisher = publisher
        self._interval_s = interval_s
        self._batch_size = batch_size
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> int:
        with self._factory() as session:
            try:
                count = publish_pending(session, self._publisher, self._batch_size)
                session.commit()
            except Exception:
                session.rollback()
                raise
        return count

    def _loop(self) -> None:
        failures = 0
        while not self._stop.is_set():
            delay = self._interval_s
            try:
                if self.run_once() >= self._batch_size:
                    delay = 0  # a full batch: more is probably waiting
                failures = 0
            except Exception as exc:  # events stay pending; never log payloads or connection text
                failures += 1
                delay = min(self._interval_s * 2**failures, MAX_BACKOFF_S)
                log.warning("outbox relay failed (%s); retry in %.0fs", type(exc).__name__, delay)
            self._stop.wait(delay)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="outbox-relay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
