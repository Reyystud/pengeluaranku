"""Idempotency keys (PRD 13.1.5), keyed by ``(user_id, key)``; ``user_id`` is always first."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def purge_expired(self, user_id: uuid.UUID, key: str, cutoff: dt.datetime) -> None:
        self.session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.key == key,
                IdempotencyKey.created_at < cutoff,
            )
        )

    def claim(
        self, user_id: uuid.UUID, key: str, method: str, path: str, request_hash: str
    ) -> bool:
        """Insert the key; ``True`` if this request owns it.

        A concurrent request with the same key blocks on the unique index until the first
        transaction ends, then sees a conflict (``False``) and can replay the stored response.
        """
        now = dt.datetime.now(dt.UTC)
        stmt = (
            insert(IdempotencyKey)
            .values(
                user_id=user_id,
                key=key,
                method=method,
                path=path,
                request_hash=request_hash,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "key"])
            .returning(IdempotencyKey.key)
        )
        return self.session.execute(stmt).first() is not None

    def get(self, user_id: uuid.UUID, key: str) -> IdempotencyKey | None:
        stmt = select(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def complete(self, user_id: uuid.UUID, key: str, status: int, body: dict[str, Any]) -> None:
        row = self.get(user_id, key)
        if row is not None:
            row.response_status = status
            row.response_body = body
            self.session.flush()
