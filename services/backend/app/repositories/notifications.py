"""In-app notifications (PRD 7.14, 12.2). Every method takes ``user_id`` first."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from app.core.ids import new_uuid7
from app.models import Notification
from app.models.base import utcnow
from app.repositories.base import ScopedRepository


class NotificationRepository(ScopedRepository[Notification]):
    model = Notification

    def create_once(
        self,
        user_id: uuid.UUID,
        *,
        type: str,
        title: str,
        body: str,
        link: str | None,
        payload: dict[str, Any],
        dedupe_key: str,
    ) -> bool:
        """Insert unless ``(user, dedupe_key)`` exists; True if a row was created (FR-05.05)."""
        stmt = (
            insert(Notification)
            .values(
                id=new_uuid7(),
                user_id=user_id,
                type=type,
                title=title,
                body=body,
                link=link,
                payload=payload,
                dedupe_key=dedupe_key,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
            .returning(Notification.id)
        )
        return self.session.execute(stmt).first() is not None  # no row back = it existed

    def page(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool,
        limit: int,
        after: tuple[dt.datetime, uuid.UUID] | None,
    ) -> list[Notification]:
        """Newest first; ``after`` is the (created_at, id) of the last row already seen."""
        stmt = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if after is not None:
            created, last_id = after
            stmt = stmt.where(
                or_(
                    Notification.created_at < created,
                    (Notification.created_at == created) & (Notification.id < last_id),
                )
            )
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        return list(self.session.execute(stmt).scalars())

    def unread_count(self, user_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        return int(self.session.execute(stmt).scalar_one())

    def mark_all_read(self, user_id: uuid.UUID) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
            .values(read_at=utcnow())
        )
        return int(self.session.execute(stmt).rowcount)  # type: ignore[attr-defined]
