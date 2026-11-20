"""Users, refresh tokens and categories (PRD 12.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Index,
    Numeric,
    SmallInteger,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_check, fk_user, pk_uuid, tstz, updated_at


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("char_length(display_name) BETWEEN 1 AND 60", name="display_name_length"),
        CheckConstraint("currency = 'IDR'", name="currency_idr"),
        enum_check("locale", "locale", ("en", "id")),
        CheckConstraint("budget_period_start_day BETWEEN 1 AND 28", name="period_start_day"),
        CheckConstraint(
            "pending_period_start_day BETWEEN 1 AND 28", name="pending_period_start_day"
        ),
        Index("ux_users_email", text("lower(email)"), unique=True),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="IDR", server_default="IDR")
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, default="Asia/Jakarta", server_default="Asia/Jakarta"
    )
    locale: Mapped[str] = mapped_column(Text, nullable=False, default="en", server_default="en")
    budget_period_start_day: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, server_default="1"
    )
    pending_period_start_day: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    pending_period_start_effective: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    training_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_user", "user_id"),
        Index("ix_refresh_family", "family_id"),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    revoked_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    expires_at: Mapped[dt.datetime] = tstz(default_now=False)
    created_at: Mapped[dt.datetime] = tstz()
    user_agent_hash: Mapped[str | None] = mapped_column(Text, nullable=True)


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        enum_check(
            "transaction_type", "transaction_type", ("income", "expense", "transfer", "any")
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_model_label: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
