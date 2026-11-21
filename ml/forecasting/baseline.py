"""Run-rate and seasonal-naive period-end forecast (PRD 7.7.1 - 7.7.4). Pure functions.

``predicted_total = spent_to_date + expected_recurring_remaining + nonrecurring_remaining``.
The caller passes the recurring charges still expected (``recurring``, from FR-08) and a history
and period-to-date figure that already exclude them, so rent on the 1st does not inflate the rate
(7.7.1). Amounts are floats only inside this module; the caller converts to ``Decimal`` at the edge.

The interval is a documented heuristic, not a calibrated one: the spread of daily spend is taken
from its 10th/90th percentiles, ``s = (P90 - P10) / spread_divisor``, and the remaining total gets
``+- z * s * sqrt(days_remaining)`` (7.7.2).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from ml.anomaly_detection.stats import percentile
from ml.forecasting.config import ForecastConfig

Method = Literal["run_rate", "seasonal_naive"]
HistoryLevel = Literal["personal", "limited"]
ExceedBand = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class CurvePoint:
    day: date
    p10: float
    p50: float
    p90: float  # cumulative period total at the end of `day`


@dataclass(frozen=True)
class Forecast:
    method: Method
    history_level: HistoryLevel
    spent_to_date: float
    expected_recurring_remaining: float
    predicted_remaining: float
    predicted_total: float
    interval_low: float
    interval_high: float
    baseline_prediction: float
    curve: tuple[CurvePoint, ...]


@dataclass(frozen=True)
class Unavailable:
    days_needed: int
    transactions_needed: int


def exceed_band(limit: float, p50: float, p90: float) -> ExceedBand:
    """7.7.4: high if L <= P50, medium if P50 < L <= P90, else low."""
    if limit <= p50:
        return "high"
    if limit <= p90:
        return "medium"
    return "low"


def spread(daily: Sequence[float], cfg: ForecastConfig) -> float:
    """Std-like spread of daily spend from its P10/P90 (0 when there is no variation)."""
    if len(daily) < 2:
        return 0.0
    return max(percentile(daily, 0.9) - percentile(daily, 0.1), 0.0) / cfg.spread_divisor


def run_rate_remaining(spent: float, days_observed: int, days_remaining: int) -> float:
    """``spent / days_observed x days_remaining`` (7.7.2)."""
    if days_remaining <= 0 or days_observed <= 0:
        return 0.0
    return spent / days_observed * days_remaining


def seasonal_daily(history: Sequence[tuple[date, float]], target: date, weeks: int) -> float:
    """Mean spend on ``target``'s weekday over the last ``weeks`` such days in ``history``."""
    same = [v for d, v in history if d.weekday() == target.weekday()][-weeks:]
    return sum(same) / len(same) if same else 0.0


def forecast(
    *,
    spent_to_date: float,
    today: date,
    period_start: date,
    period_end: date,
    history: Sequence[tuple[date, float]],
    history_days: int,
    transactions: int,
    require_transactions: bool,
    cfg: ForecastConfig,
    nonrecurring_spent_to_date: float | None = None,
    recurring: Sequence[tuple[date, float]] = (),
) -> Forecast | Unavailable:
    """Forecast the period total from ``history`` = zero-filled (day, spend) up to ``today``.

    ``history`` and ``nonrecurring_spent_to_date`` (default: ``spent_to_date``) leave out expenses
    linked to a recurring series; ``recurring`` lists the ``(day, amount)`` charges still expected
    up to ``period_end``. A charge dated today or earlier lands on the first remaining day.

    ``history_days`` is the age of the user's first transaction in days (inclusive), also used as
    the number of observed days when the user joined inside the period. ``require_transactions``
    applies the per-category minimum of FR-07.01.
    """
    days_needed = max(cfg.min_history_days - history_days, 0)
    if require_transactions:
        days_needed = max(cfg.personal_history_days - history_days, 0)
    tx_needed = max(cfg.min_category_transactions - transactions, 0) if require_transactions else 0
    if days_needed or tx_needed:
        return Unavailable(days_needed, tx_needed)

    personal = history_days >= cfg.personal_history_days
    elapsed = (today - period_start).days + 1
    remaining_days = max((period_end - today).days, 0)
    observed = max(min(elapsed, history_days), 1)
    nonrecurring_spent = (
        spent_to_date if nonrecurring_spent_to_date is None else nonrecurring_spent_to_date
    )
    baseline_remaining = run_rate_remaining(nonrecurring_spent, observed, remaining_days)
    recurring_total = sum(amount for _, amount in recurring)

    window = [v for _, v in history[-cfg.spread_window_days :]]
    s = spread(window, cfg)
    method: Method = "seasonal_naive" if personal else "run_rate"
    curve: list[CurvePoint] = []
    nonrecurring_remaining = 0.0
    for k in range(1, remaining_days + 1):
        day = today + timedelta(days=k)
        if personal:
            daily = seasonal_daily(history, day, cfg.seasonal_weeks)
        else:
            daily = baseline_remaining / remaining_days
        nonrecurring_remaining += daily
        recurring_so_far = sum(a for d, a in recurring if d <= day)
        cumulative = spent_to_date + nonrecurring_remaining + recurring_so_far
        width = cfg.z * s * math.sqrt(k)
        curve.append(
            CurvePoint(
                day,
                max(cumulative - width, spent_to_date + recurring_so_far),
                cumulative,
                cumulative + width,
            )
        )
    width_total = cfg.z * s * math.sqrt(remaining_days)
    total = spent_to_date + recurring_total + nonrecurring_remaining
    return Forecast(
        method=method,
        history_level="personal" if personal else "limited",
        spent_to_date=spent_to_date,
        expected_recurring_remaining=recurring_total,
        predicted_remaining=recurring_total + nonrecurring_remaining,
        predicted_total=total,
        interval_low=max(total - width_total, spent_to_date + recurring_total),
        interval_high=total + width_total,
        baseline_prediction=spent_to_date + recurring_total + baseline_remaining,
        curve=tuple(curve),
    )
