"""Recurring series models (PRD 7.8, 13.2). Amounts are strings; ``confidence`` and the CV are
plain numbers (ratios, not money)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.transactions import Amount, CategoryRef

Frequency = Literal["weekly", "biweekly", "monthly", "quarterly", "yearly"]
SeriesStatus = Literal["active", "paused", "ended", "user_confirmed", "user_rejected"]
UserStatus = Literal["user_confirmed", "user_rejected"]


class AmountChangeOut(BaseModel):
    """FR-08.03: the latest charge against the median of the charges before it."""

    previous_amount: str
    latest_amount: str


class RecurringOut(BaseModel):
    id: uuid.UUID
    merchant_key: str
    merchant_display: str
    transaction_type: Literal["income", "expense"]
    category: CategoryRef
    frequency: Frequency
    median_interval_days: float
    expected_amount: str  # detected (median of the last 3)
    user_expected_amount: str | None  # set by the user (FR-08.05)
    effective_amount: str  # what totals and the forecast use
    monthly_equivalent: str
    amount_cv: float
    last_date: dt.date
    next_expected_date: dt.date
    occurrences: int
    confidence: float
    status: SeriesStatus
    amount_change: AmountChangeOut | None


class RecurringList(BaseModel):
    items: list[RecurringOut]  # sorted by next_expected_date; rejected series are not listed
    monthly_expense_total: str  # active and confirmed expense series, monthly equivalent
    monthly_income_total: str
    upcoming: list[RecurringOut]  # active/confirmed, due from today to today + 7 days
    detection_version: str


class RecurringPatch(BaseModel):
    """FR-08.05. ``user_expected_amount: null`` clears the user's amount."""

    model_config = ConfigDict(extra="forbid")

    status: UserStatus | None = None
    user_expected_amount: Amount | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> RecurringPatch:
        if not self.model_fields_set & {"status", "user_expected_amount"}:
            raise ValueError("send status and/or user_expected_amount")
        return self
