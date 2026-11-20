"""Budget and notification models (PRD 7.5, 7.14, 13.2). Money and percentages are strings."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.transactions import CategoryRef

BudgetStatus = Literal["healthy", "normal", "warning", "exceeded"]
MAX_LIMIT_AMOUNT = Decimal("9999999999999.99")  # NUMERIC(15,2)
MAX_THRESHOLDS = 10


def _thresholds(value: list[int] | None) -> list[int] | None:
    """FR-05.05: sorted unique integers in 1..200."""
    if value is None:
        return None
    if len(set(value)) > MAX_THRESHOLDS:
        raise ValueError("at most 10 thresholds")
    if any(not 1 <= v <= 200 for v in value):
        raise ValueError("thresholds must be between 1 and 200")
    return sorted(set(value))


def _limit(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite() or value <= 0:
        raise ValueError("limit must be greater than 0")
    if value > MAX_LIMIT_AMOUNT:
        raise ValueError("limit is too large")
    if value.as_tuple().exponent < -2:  # type: ignore[operator]
        raise ValueError("at most 2 decimal places")
    return value


class BudgetCreate(BaseModel):
    category: str | None = Field(default=None, max_length=64)  # slug or id; null = overall
    limit_amount: Decimal
    alert_thresholds: list[int] | None = None  # default [80, 100]

    _check_limit = field_validator("limit_amount")(_limit)
    _check_thresholds = field_validator("alert_thresholds")(_thresholds)


class BudgetUpdate(BaseModel):
    limit_amount: Decimal | None = None
    alert_thresholds: list[int] | None = None

    _check_limit = field_validator("limit_amount")(_limit)
    _check_thresholds = field_validator("alert_thresholds")(_thresholds)


class BudgetPeriod(BaseModel):
    start: dt.date
    end: dt.date  # inclusive
    period_id: str
    days_in_period: int
    days_elapsed: int


class BudgetOut(BaseModel):
    id: uuid.UUID
    category: CategoryRef | None  # null = overall budget
    limit_amount: Decimal
    alert_thresholds: list[int]
    spent: Decimal
    remaining: Decimal  # may be negative when exceeded
    utilization: Decimal  # percent, 1 decimal
    status: BudgetStatus
    projected: (
        Literal["on_track", "may_exceed"] | None
    )  # needs the forecast (T-24): null until then
    period: BudgetPeriod
    created_at: dt.datetime
    updated_at: dt.datetime


class BudgetList(BaseModel):
    items: list[BudgetOut]
    category_limits_exceed_overall: bool  # FR-05.09: non-blocking warning for the UI


class BudgetHistoryItem(BaseModel):
    period_id: dt.date
    limit_amount: Decimal
    spent: Decimal
    utilization: Decimal  # percent, 1 decimal


class BudgetHistory(BaseModel):
    items: list[BudgetHistoryItem]  # newest first


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    body: str
    link: str | None
    payload: dict[str, Any]
    read_at: dt.datetime | None
    created_at: dt.datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None


class UnreadCount(BaseModel):
    count: int


class ReadAllOut(BaseModel):
    updated: int
