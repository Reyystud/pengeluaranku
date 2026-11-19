"""Idempotency, outbox, processed events, deletion requests and job runs (PRD 12.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, Index, Integer, SmallInteger, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_check, fk_user, pk_uuid, tstz


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (CheckConstraint("char_length(key) BETWEEN 8 AND 128", name="key_length"),)

    user_id: Mapped[uuid.UUID] = fk_user(primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    response_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    response_body: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = tstz()


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_pending",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()  # equals the event_id
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # no FK on purpose
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = tstz()
    published_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    consumer: Mapped[str] = mapped_column(Text, primary_key=True)
    processed_at: Mapped[dt.datetime] = tstz()


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"

    user_pseudo_id: Mapped[str] = mapped_column(Text, primary_key=True)
    requested_at: Mapped[dt.datetime] = tstz()
    purged_at: Mapped[dt.datetime | None] = tstz(nullable=True)


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (enum_check("status", "status", ("running", "succeeded", "failed")),)

    id: Mapped[uuid.UUID] = pk_uuid()
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[dt.datetime] = tstz()
    finished_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    stats: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
