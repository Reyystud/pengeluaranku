"""Forecast models (PRD 7.7, 13.2). Amounts are strings; the response is either a forecast or an
"unavailable" notice (HTTP 200 both ways, discriminated by ``available``)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel

from app.schemas.budgets import BudgetPeriod
from app.schemas.transactions import CategoryRef

ForecastMethod = Literal["run_rate", "seasonal_naive", "model"]
ExceedBand = Literal["low", "medium", "high"]


class CurvePointOut(BaseModel):
    date: dt.date
    p10: str
    p50: str
    p90: str  # cumulative period total at the end of that day


class ForecastBudget(BaseModel):
    limit_amount: str
    predicted_over_budget: str  # predicted_total - limit; negative when under
    exceed_band: ExceedBand


class ForecastOut(BaseModel):
    available: Literal[True] = True
    period: BudgetPeriod
    category: CategoryRef | None
    spent_to_date: str
    predicted_total: str
    interval_low: str
    interval_high: str
    predicted_remaining: str
    expected_recurring_remaining: str
    baseline_prediction: str
    method: ForecastMethod
    history_level: Literal["personal", "limited"]
    model_version: str | None
    generated_at: dt.datetime
    budget: ForecastBudget | None
    estimated_period_end_balance: str | None  # overall only
    daily_curve: list[CurvePointOut]


class ForecastUnavailable(BaseModel):
    available: Literal[False] = False
    reason: Literal["INSUFFICIENT_HISTORY"] = "INSUFFICIENT_HISTORY"
    days_needed: int
    transactions_needed: int


ForecastResponse = ForecastOut | ForecastUnavailable
