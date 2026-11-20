"""Typed view of ``config/forecast.yaml`` (PRD 7.7, 0.3 rule 3)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ml.config import _load_yaml


@dataclass(frozen=True)
class ForecastConfig:
    version: str
    min_history_days: int
    personal_history_days: int
    min_category_transactions: int
    spread_window_days: int
    z: float
    spread_divisor: float
    seasonal_weeks: int
    cache_max_age_hours: int
    keep_per_series: int


@lru_cache(maxsize=1)
def load_forecast_config() -> ForecastConfig:
    d = _load_yaml("forecast.yaml")
    return ForecastConfig(
        version=str(d["version"]),
        min_history_days=int(d["min_history_days"]),
        personal_history_days=int(d["personal_history_days"]),
        min_category_transactions=int(d["min_category_transactions"]),
        spread_window_days=int(d["spread_window_days"]),
        z=float(d["interval"]["z"]),
        spread_divisor=float(d["interval"]["spread_divisor"]),
        seasonal_weeks=int(d["seasonal_naive"]["weeks"]),
        cache_max_age_hours=int(d["cache"]["max_age_hours"]),
        keep_per_series=int(d["cache"]["keep_per_series"]),
    )
