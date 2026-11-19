"""Budgets, anomalies, forecasts, recurring series, insights, notifications (PRD 12.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_check, fk_user, money, pk_uuid, tstz, updated_at

NIL_UUID = "'00000000-0000-0000-0000-000000000000'::uuid"


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("limit_amount > 0", name="limit_positive"),
        Index(
            "ux_budget_user_cat", "user_id", text(f"COALESCE(category_id, {NIL_UUID})"), unique=True
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=True
    )
    limit_amount: Mapped[Decimal] = money()
    alert_thresholds: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger),
        nullable=False,
        default=lambda: [80, 100],
        server_default=text("'{80,100}'"),
    )
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class BudgetPeriodSnapshot(Base):
    __tablename__ = "budget_period_snapshots"
    __table_args__ = (Index("ix_bps_user_period", "user_id", "period_id"),)

    budget_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("budgets.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = fk_user()
    period_id: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    limit_amount: Mapped[Decimal] = money()
    spent: Mapped[Decimal] = money()
    utilization: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    created_at: Mapped[dt.datetime] = tstz()


class Anomaly(Base):
    __tablename__ = "anomalies"
    __table_args__ = (
        enum_check(
            "anomaly_type",
            "anomaly_type",
            (
                "amount_spike",
                "frequency_burst",
                "new_merchant_high_value",
                "category_surge",
                "amount_low",
            ),
        ),
        enum_check("severity", "severity", ("low", "medium", "high")),
        enum_check(
            "status", "status", ("open", "confirmed", "dismissed", "historical", "superseded")
        ),
        enum_check("history_level", "history_level", ("personal", "limited")),
        enum_check(
            "feedback_reason",
            "feedback_reason",
            ("expected_purchase", "wrong_amount", "not_mine", "other"),
        ),
        Index(
            "ux_anom_tx_type",
            "transaction_id",
            "anomaly_type",
            unique=True,
            postgresql_where=text("transaction_id IS NOT NULL AND status <> 'superseded'"),
        ),
        Index(
            "ux_anom_surge_open",
            "user_id",
            "category_id",
            unique=True,
            postgresql_where=text("anomaly_type = 'category_surge' AND status = 'open'"),
        ),
        Index("ix_anom_user", "user_id", text("created_at DESC")),
        Index("ix_anom_alerts", "user_id", "period_id", postgresql_where=text("is_alert")),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=True
    )
    anomaly_type: Mapped[str] = mapped_column(Text, nullable=False)
    anomaly_score: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    is_alert: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    history_level: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[Any] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    feature_version: Mapped[str] = mapped_column(Text, nullable=False)
    period_id: Mapped[dt.date] = mapped_column(Date, nullable=False)
    transaction_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class AnomalySuppression(Base):
    __tablename__ = "anomaly_suppressions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    merchant_key: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[dt.datetime] = tstz(default_now=False)


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        enum_check("method", "method", ("run_rate", "seasonal_naive", "model")),
        enum_check("history_level", "history_level", ("personal", "limited")),
        Index("ix_fc_lookup", "user_id", "period_id", "category_id", text("as_of DESC")),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    period_id: Mapped[dt.date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=True
    )
    as_of: Mapped[dt.datetime] = tstz(default_now=False)
    spent_to_date: Mapped[Decimal] = money()
    predicted_total: Mapped[Decimal] = money()
    interval_low: Mapped[Decimal] = money()
    interval_high: Mapped[Decimal] = money()
    baseline_prediction: Mapped[Decimal] = money()
    expected_recurring_remaining: Mapped[Decimal] = money(default=Decimal("0"), server_default="0")
    method: Mapped[str] = mapped_column(Text, nullable=False)
    history_level: Mapped[str] = mapped_column(Text, nullable=False)
    daily_curve: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = tstz()


class ForecastOutcome(Base):
    __tablename__ = "forecast_outcomes"
    __table_args__ = (
        Index(
            "ux_fc_outcome",
            "user_id",
            "period_id",
            text(f"COALESCE(category_id, {NIL_UUID})"),
            "forecast_day",
            unique=True,
        ),
    )

    # The DDL sketch has no primary key; the ORM needs one, so a surrogate id is added.
    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    period_id: Mapped[dt.date] = mapped_column(Date, nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    forecast_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    predicted_total: Mapped[Decimal] = money()
    baseline_prediction: Mapped[Decimal] = money()
    actual_total: Mapped[Decimal] = money()
    model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = tstz()


class RecurringSeries(Base):
    __tablename__ = "recurring_series"
    __table_args__ = (
        enum_check("transaction_type", "transaction_type", ("income", "expense")),
        enum_check(
            "frequency", "frequency", ("weekly", "biweekly", "monthly", "quarterly", "yearly")
        ),
        enum_check(
            "status", "status", ("active", "paused", "ended", "user_confirmed", "user_rejected")
        ),
        UniqueConstraint(
            "user_id",
            "merchant_key",
            "transaction_type",
            name="uq_recurring_series_user_merchant_type",
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    merchant_key: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_display: Mapped[str] = mapped_column(Text, nullable=False)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("categories.id"), nullable=False
    )
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    median_interval_days: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    expected_amount: Mapped[Decimal] = money()
    amount_cv: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    last_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    next_expected_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    user_expected_amount: Mapped[Decimal | None] = money(nullable=True)
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class RecurringSeriesTransaction(Base):
    __tablename__ = "recurring_series_transactions"

    series_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("recurring_series.id", ondelete="CASCADE"), primary_key=True
    )
    transaction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True
    )


class Insight(Base):
    __tablename__ = "insights"
    __table_args__ = (
        enum_check("severity", "severity", ("info", "positive", "warning")),
        UniqueConstraint(
            "user_id",
            "rule_id",
            "period_id",
            "subject_key",
            name="uq_insights_user_rule_period_subject",
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    period_id: Mapped[dt.date] = mapped_column(Date, nullable=False)
    subject_key: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    message_key: Mapped[str] = mapped_column(Text, nullable=False)
    message_params: Mapped[Any] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[Any] = mapped_column(JSONB, nullable=False)
    dismissed_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    created_at: Mapped[dt.datetime] = tstz()
    updated_at: Mapped[dt.datetime] = updated_at()


class UserSegment(Base):
    __tablename__ = "user_segments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    segment_id: Mapped[str] = mapped_column(Text, nullable=False)
    traits: Mapped[Any] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[dt.datetime] = tstz(default_now=False)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        enum_check(
            "type",
            "type",
            (
                "budget_threshold",
                "anomaly_alert",
                "import_completed",
                "recurring_due_soon",
                "review_queue",
            ),
        ),
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index(
            "ix_notif_unread",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = pk_uuid()
    user_id: Mapped[uuid.UUID] = fk_user()
    type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[Any] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[dt.datetime | None] = tstz(nullable=True)
    created_at: Mapped[dt.datetime] = tstz()
