"""Transactions and categorization tables (PRD 12.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_check, fk_user, money, pk_uuid, tstz, updated_at

PAYMENT_METHODS = (
    "cash",
    "bank_transfer",
    "debit_card",
    "credit_card",
    "e_wallet",
    "qris",
    "other",
)
CATEGORY_STATUSES = ("auto", "suggested", "needs_review", "rule", "user_set", "user_confirmed")
DECISIONS = ("auto_apply", "suggest", "needs_review")


class TransactionImport(Base):
    __tablename__ = "transaction_imports"
    __table_args__ = (
        enum_check("status", "status", ("previewed", "committed", "failed", "expired")),
        enum_check("commit_mode", "commit_mode", ("strict", "skip_invalid")),
        Index("ix_imports_user", "user_id", text("created_at DESC")),
        Index("ix_imports_sha", "user_id", "file_sha256"),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    status: Mapped[str] = mapped_column(Text, nullable=False)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    staged_rows: Mapped[Any] = mapped_column(JSONB, nullable=False)
    committed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[dt.datetime] = tstz(default_now=False)
    created_at: Mapped[dt.datetime] = tstz()
    committed_at: Mapped[dt.datetime | None] = tstz(nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        enum_check("transaction_type", "transaction_type", ("income", "expense", "transfer")),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("char_length(description) BETWEEN 1 AND 200", name="description_length"),
        CheckConstraint("char_length(merchant) <= 100", name="merchant_length"),
        enum_check("payment_method", "payment_method", PAYMENT_METHODS),
        enum_check("category_status", "category_status", CATEGORY_STATUSES),
        CheckConstraint("char_length(notes) <= 500", name="notes_length"),
        enum_check("source", "source", ("manual", "csv", "demo_seed")),
        Index("ix_tx_user_date", "user_id", text("transaction_date DESC"), text("id DESC")),
        Index("ix_tx_user_cat_date", "user_id", "category_id", text("transaction_date DESC")),
        Index("ix_tx_user_merchant", "user_id", "merchant_key", text("transaction_date DESC")),
        Index(
            "ix_tx_user_status",
            "user_id",
            "category_status",
            postgresql_where=text("category_status IN ('suggested','needs_review')"),
        ),
        Index(
            "ix_tx_dup_lookup",
            "user_id",
            "transaction_type",
            "amount",
            "merchant_key",
            "transaction_date",
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = money()
    description: Mapped[str] = mapped_column(Text, nullable=False)
    merchant: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant_key: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    transaction_date: Mapped[dt.datetime] = tstz(default_now=False)
    has_time: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    payment_method: Mapped[str] = mapped_column(
        Text, nullable=False, default="other", server_default="other"
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    category_status: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    import_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transaction_imports.id", ondelete="SET NULL"), nullable=True
    )
    possible_duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_dismissed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class CategoryPrediction(Base):
    __tablename__ = "category_predictions"
    __table_args__ = (
        enum_check("source", "source", ("model", "user_rule", "fallback")),
        enum_check("decision", "decision", DECISIONS),
        Index("ix_pred_tx", "transaction_id", text("created_at DESC")),
        Index("ix_pred_user", "user_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = fk_user()
    source: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    alternatives: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    feature_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ml_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = tstz()


class MerchantRule(Base):
    __tablename__ = "merchant_rules"
    __table_args__ = (
        CheckConstraint("merchant_key <> ''", name="merchant_key_not_empty"),
        UniqueConstraint("user_id", "merchant_key", name="uq_merchant_rules_user_id_merchant_key"),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    merchant_key: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_display: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    times_applied: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_applied_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class CategoryFeedback(Base):
    __tablename__ = "category_feedback"
    __table_args__ = (
        enum_check("feedback_type", "feedback_type", ("correction", "confirmation", "quick_pick")),
        Index("ix_cfb_user", "user_id", text("created_at DESC")),
        Index("ix_cfb_tx", "transaction_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False
    )
    prediction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("category_predictions.id", ondelete="SET NULL"), nullable=True
    )
    previous_category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    new_category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    previous_status: Mapped[str] = mapped_column(Text, nullable=False)
    feedback_type: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    merchant_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = tstz()
