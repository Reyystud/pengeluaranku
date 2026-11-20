"""Analytics response models (PRD 7.4, 13.2). Money is a string; percentages are strings too."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

RangeName = Literal["current_period", "previous_period", "last_3_periods", "custom"]
Granularity = Literal["day", "week", "month"]


class PeriodInfo(BaseModel):
    range: RangeName
    start: dt.date
    end: dt.date  # inclusive
    period_id: str | None  # YYYY-MM-DD of the period start; null for multi-period/custom ranges
    days_in_period: int
    days_elapsed: int  # inclusive of today; 0 before the range starts, full length after it ends
    in_progress: bool
    timezone: str


class Figures(BaseModel):
    start: dt.date
    end: dt.date
    income: Decimal
    expenses: Decimal
    net: Decimal
    savings_rate: Decimal | None  # percent, 1 decimal; null when income is 0


class Changes(BaseModel):
    """Percent change (cur - prev) / prev, 1 decimal; null when the previous value is 0."""

    income: Decimal | None
    expenses: Decimal | None
    net: Decimal | None


class Comparison(BaseModel):
    label: str  # e.g. "vs. same point last period"
    current: Figures  # what was compared (to date when the range is in progress)
    previous: Figures
    change: Changes


class SummaryOut(BaseModel):
    period: PeriodInfo
    balance: Decimal  # all time, up to now
    income: Decimal
    expenses: Decimal
    net: Decimal
    savings_rate: Decimal | None
    income_count: int
    expense_count: int
    comparison: Comparison
    review_queue_count: int


class CategoryItem(BaseModel):
    slug: str
    name: str
    amount: Decimal
    share: Decimal  # percent of total expenses, 1 decimal
    count: int


class CategoriesOut(BaseModel):
    period: PeriodInfo
    total_expenses: Decimal
    items: list[CategoryItem]


class TrendPoint(BaseModel):
    start: dt.date
    end: dt.date
    expenses: Decimal
    cumulative: Decimal | None  # null for buckets entirely in the future
    future: bool
    budget_pace: Decimal | None


class TrendsOut(BaseModel):
    period: PeriodInfo
    granularity: Granularity
    budget_limit: Decimal | None
    series: list[TrendPoint]


class MerchantItem(BaseModel):
    merchant_key: str
    name: str
    amount: Decimal
    count: int


class MerchantsOut(BaseModel):
    period: PeriodInfo
    items: list[MerchantItem]


class MethodItem(BaseModel):
    payment_method: str
    amount: Decimal
    share: Decimal
    count: int


class MethodsOut(BaseModel):
    period: PeriodInfo
    total_expenses: Decimal
    items: list[MethodItem]
