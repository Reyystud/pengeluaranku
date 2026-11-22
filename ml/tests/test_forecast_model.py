"""Forecast model experiment (PRD 7.7.3, 9.4): origin features, leakage, metrics, ship rule."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from ml.forecasting.baseline import seasonal_daily
from ml.forecasting.model_eval import (
    FEATURES,
    UserSeries,
    mase_scale,
    origin_row,
    seasonal_remaining,
    ship_decision,
    summarize,
    wape,
)


def series(n: int = 120) -> UserSeries:
    rng = np.random.default_rng(3)
    start = pd.Timestamp("2025-01-01")
    rows = [
        {
            "occurred_at": start + pd.Timedelta(days=i),
            "type": "expense",
            "amount_f": float(rng.integers(10, 90)) * 1000,
            "recurring_series_id": None,
        }
        for i in range(n)
    ]
    rows.append(
        {
            "occurred_at": start + pd.Timedelta(days=5),
            "type": "expense",
            "amount_f": 999999.0,
            "recurring_series_id": "x-sub0",
        }
    )
    rows.append(
        {
            "occurred_at": start + pd.Timedelta(days=9),
            "type": "income",
            "amount_f": 5e6,
            "recurring_series_id": None,
        }
    )
    return UserSeries(pd.DataFrame(rows), start.date() + timedelta(days=n - 1))


def test_fr_07_recurring_expenses_are_not_part_of_the_target() -> None:
    s = series()
    assert s.y[5] < 100000  # the 999,999 recurring charge is excluded
    assert s.income[9] and not s.income[8]


def test_fr_07_origin_features_do_not_see_the_future() -> None:
    s = series()
    i, ps, pe = 70, 60, 89
    before = origin_row(s, i, ps, pe, set(), 4)
    s.y[i + 1 :] = s.y[i + 1 :] * 1000 + 7  # change everything after the origin
    after = origin_row(s, i, ps, pe, set(), 4)
    assert before == after
    assert list(before[0]) == list(FEATURES)


def test_fr_07_seasonal_remaining_matches_the_baseline_rule() -> None:
    s = series()
    i, h = 80, 10
    history = list(zip(s.days[: i + 1], s.y[: i + 1].tolist(), strict=True))
    expected = sum(
        seasonal_daily(history, s.days[i] + timedelta(days=k), 4) for k in range(1, h + 1)
    )
    assert np.isclose(seasonal_remaining(s, i, h, 4), expected)


def test_fr_07_metrics_wape_mase_and_coverage() -> None:
    assert wape(np.array([10.0, -10.0]), np.array([100.0, 100.0])) == 0.1
    s = series()
    assert mase_scale(s, 100, 10, 7, 60) > 0
    assert np.isnan(mase_scale(s, 5, 10, 7, 60))
    df = pd.DataFrame(
        {
            "origin_day": [5, 5],
            "archetype": ["a", "a"],
            "actual": [100.0, 200.0],
            "mase_scale": [10.0, 10.0],
            "m_p50": [110.0, 190.0],
            "m_low": [90.0, 250.0],
            "m_high": [120.0, 300.0],
        }
    )
    out = summarize(df, ["m"])["overall"]["m"]
    assert out["wape"] == 20 / 300 and out["mae"] == 10.0 and out["mase"] == 1.0
    assert out["coverage"] == 0.5


def test_fr_07_ship_rule_needs_lower_wape_on_every_origin_day_and_coverage_in_band() -> None:
    cfg = {"ship_rule": {"coverage_min": 0.7, "coverage_max": 0.9}}

    def block(model_wape: float, cov: float) -> dict[str, dict[str, float]]:
        return {
            "run_rate": {"wape": 0.3},
            "baseline": {"wape": 0.22},
            "ets": {"wape": model_wape, "coverage": cov},
            "lightgbm_quantile": {"wape": 0.4, "coverage": 0.8},
        }

    summary = {
        "overall": block(0.2, 0.8),
        "by_origin_day": {5: block(0.2, 0.8), 10: block(0.25, 0.8)},
    }
    assert ship_decision(summary, cfg)[0]["ships"] is True
    assert ship_decision(summary, cfg)[0]["beats_seasonal_naive"] is False  # 0.25 vs 0.22 on day 10
    assert ship_decision(summary, cfg)[1]["ships"] is False  # LightGBM worse than run-rate
    summary["overall"] = block(0.2, 0.95)
    assert ship_decision(summary, cfg)[0]["ships"] is False  # coverage out of band
    summary["overall"] = block(0.2, 0.8)
    summary["by_origin_day"][10] = block(0.35, 0.8)
    assert ship_decision(summary, cfg)[0]["ships"] is False  # worse on one origin day
