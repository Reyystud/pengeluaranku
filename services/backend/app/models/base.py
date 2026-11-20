"""Declarative base, column helpers and constraint naming for all tables (PRD 12.1).

Conventions: UUIDv7 primary keys generated in the app, ``TIMESTAMPTZ`` in UTC, money as
``NUMERIC(15,2)`` (``Decimal`` in Python), enums as ``TEXT`` + ``CHECK``, snake_case plural
table names. ``updated_at`` is set by the application layer, not by triggers.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, MetaData, Numeric, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import new_uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def enum_check(name: str, column: str, values: tuple[str, ...]) -> CheckConstraint:
    """``TEXT`` enum as a named CHECK constraint (PRD 4.8)."""
    return CheckConstraint(f"{column} IN ({quoted(values)})", name=name)


def pk_uuid() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=new_uuid7)


def fk_user(**kw: Any) -> Mapped[uuid.UUID]:
    """``user_id`` column for user-owned tables: ``NOT NULL`` FK with ``ON DELETE CASCADE``."""
    from sqlalchemy import ForeignKey

    return mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, **kw)


def tstz(nullable: bool = False, default_now: bool = True) -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=nullable,
        default=utcnow if default_now and not nullable else None,
    )


def money(nullable: bool = False, **kw: Any) -> Mapped[Decimal]:
    return mapped_column(Numeric(15, 2), nullable=nullable, **kw)


def updated_at() -> Mapped[dt.datetime]:
    """``updated_at`` maintained by the application layer (PRD 12.1)."""
    return mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
