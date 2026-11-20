"""Notifications API (PRD 7.14, 13.2): list, unread count, mark read."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import not_found
from app.models import Notification
from app.models.base import utcnow
from app.repositories import NotificationRepository
from app.schemas.budgets import NotificationOut, NotificationPage, ReadAllOut, UnreadCount

router = APIRouter(prefix="/notifications", tags=["notifications"])
SORT = "created"


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        link=n.link,
        payload=n.payload,
        read_at=n.read_at,
        created_at=n.created_at,
    )


@router.get("", response_model=NotificationPage)
def list_notifications(
    session: SessionDep,
    user: CurrentUser,
    settings: SettingsDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> NotificationPage:
    secret = settings.cursor_signing_key.get_secret_value()
    after = None
    if cursor:
        c = decode_cursor(cursor, user.id, secret, SORT)
        after = (dt.datetime.fromisoformat(c.key), c.id)
    rows = NotificationRepository(session).page(
        user.id, unread_only=unread_only, limit=limit + 1, after=after
    )
    page, more = rows[:limit], len(rows) > limit
    next_cursor = None
    if more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            Cursor(sort=SORT, key=last.created_at.isoformat(), id=last.id), user.id, secret
        )
    return NotificationPage(items=[_out(n) for n in page], next_cursor=next_cursor)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(session: SessionDep, user: CurrentUser) -> UnreadCount:
    return UnreadCount(count=NotificationRepository(session).unread_count(user.id))


@router.post("/read-all", response_model=ReadAllOut)
def read_all(session: SessionDep, user: CurrentUser) -> ReadAllOut:
    return ReadAllOut(updated=NotificationRepository(session).mark_all_read(user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> NotificationOut:
    note = NotificationRepository(session).get(user.id, notification_id)
    if note is None:
        raise not_found()
    if note.read_at is None:
        note.read_at = utcnow()
        session.flush()
    return _out(note)
