"""Transactional outbox (PRD 6.3, 14.3): events are written in the change's own DB transaction.

A publisher/worker (later task) reads unpublished rows. Payloads carry ids and enums only, never
descriptions, merchants, notes or amounts (PRD 17.3).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.ids import new_uuid7
from app.models import OutboxEvent

SCHEMA_VERSION = 1


def enqueue(
    session: Session,
    event_type: str,
    *,
    user_id: uuid.UUID,
    aggregate_id: uuid.UUID,
    request_id: str | None,
    data: dict[str, Any],
) -> OutboxEvent:
    event_id = new_uuid7()
    envelope = {
        "event_id": str(event_id),
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "occurred_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "request_id": request_id,
        "user_id": str(user_id),
        "data": data,
    }
    row = OutboxEvent(
        id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        user_id=user_id,
        payload=envelope,
    )
    session.add(row)
    return row
