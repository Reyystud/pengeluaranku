"""Run-rate / seasonal-naive forecast (PRD 7.7): formulas, minimum history, interval, band."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ml.forecasting import Forecast, Unavailable, exceed_band, forecast, load_forecast_config
from ml.forecasting.baseline import run_rate_remaining, seasonal_daily, spread

CFG = load_forecast_config()
START, END = date(2026, 11, 1), date(2026, 11, 30)


def hist(days: int, today: date, per_day: float = 100_000.0) -> list[tuple[date, float]]:
    return [(today - timedelta(days=days - 1 - i), per_day) for i in range(days)]


def run(
    today: date = date(2026, 11, 10),
    spent: float = 1_000_000.0,
    history_days: int = 20,
    per_day: float = 100_000.0,
    transactions: int = 100,
    category: bool = False,
) -> Forecast | Unavailable:
    return forecast(
        spent_to_date=spent,
        today=today,
        period_start=START,
        period_end=END,
        history=hist(history_days, today, per_day),
        history_days=history_days,
        transactions=transactions,
        require_transactions=category,
        cfg=CFG,
    )


def ok(result: Forecast | Unavailable) -> Forecast:
    assert isinstance(result, Forecast), result
    return result


def test_fr_07_config_comes_from_the_versioned_file() -> None:
    assert CFG.version == "run-rate-2"
    assert (CFG.min_history_days, CFG.personal_history_days, CFG.min_category_transactions) == (
        14,
        60,
        20,
    )
    assert CFG.cache_max_age_hours == 6 and CFG.seasonal_weeks == 4


def test_fr_07_02_run_rate_is_spend_per_observed_day_times_days_left() -> None:
    f = ok(run())  # 10 days elapsed, Rp1.000.000 spent, 20 days left
    assert f.method == "run_rate" and f.history_level == "limited"
    assert f.predicted_remaining == pytest.approx(2_000_000)
    assert f.predicted_total == pytest.approx(3_000_000)
    assert f.baseline_prediction == pytest.approx(3_000_000)
    assert f.expected_recurring_remaining == 0.0  # until recurring detection (T-30)
    assert f.interval_low <= f.predicted_total <= f.interval_high


def test_fr_07_02_a_user_who_joined_mid_period_is_divided_by_observed_days() -> None:
    # 15 days of history but 25 days elapsed in the period: spent covers only 15 days.
    f = ok(run(today=date(2026, 11, 25), spent=1_500_000, history_days=15, per_day=100_000))
    assert f.predicted_remaining == pytest.approx(1_500_000 / 15 * 5)


def test_fr_07_02_less_than_two_weeks_is_not_shown_and_says_how_many_days_are_missing() -> None:
    u = run(history_days=10)
    assert u == Unavailable(days_needed=4, transactions_needed=0)
    assert isinstance(run(history_days=14), Forecast)


def test_fr_07_01_category_needs_60_days_and_20_transactions() -> None:
    assert run(history_days=40, transactions=30, category=True) == Unavailable(20, 0)
    assert run(history_days=90, transactions=12, category=True) == Unavailable(0, 8)
    assert isinstance(run(history_days=90, transactions=20, category=True), Forecast)


def test_fr_07_02_sixty_days_switches_to_seasonal_naive_by_weekday() -> None:
    today = date(2026, 11, 10)  # a Tuesday
    history = [
        (
            today - timedelta(days=89 - i),
            300_000.0 if (today - timedelta(days=89 - i)).weekday() >= 5 else 50_000.0,
        )
        for i in range(90)
    ]
    f = forecast(
        spent_to_date=500_000,
        today=today,
        period_start=START,
        period_end=END,
        history=history,
        history_days=90,
        transactions=500,
        require_transactions=False,
        cfg=CFG,
    )
    assert isinstance(f, Forecast)
    assert f.method == "seasonal_naive" and f.history_level == "personal"
    weekend_days = sum(1 for k in range(1, 21) if (today + timedelta(days=k)).weekday() >= 5)
    expected = weekend_days * 300_000 + (20 - weekend_days) * 50_000
    assert f.predicted_remaining == pytest.approx(expected)
    assert f.baseline_prediction == pytest.approx(
        500_000 + 500_000 / 10 * 20
    )  # run-rate stays reported


def test_fr_07_seasonal_daily_uses_the_last_four_same_weekdays() -> None:
    mondays = [(date(2026, 11, 2) - timedelta(days=7 * k), float(k)) for k in range(6, -1, -1)]
    assert seasonal_daily(mondays, date(2026, 11, 9), 4) == pytest.approx((3 + 2 + 1 + 0) / 4)
    assert seasonal_daily([], date(2026, 11, 9), 4) == 0.0


def test_fr_07_the_interval_is_zero_wide_without_variation_and_grows_with_it() -> None:
    flat = ok(run())
    assert flat.interval_low == pytest.approx(flat.predicted_total)
    assert flat.interval_high == pytest.approx(flat.predicted_total)
    today = date(2026, 11, 10)
    history = [
        (today - timedelta(days=19 - i), 20_000.0 if i % 2 else 180_000.0) for i in range(20)
    ]
    wide = ok(
        forecast(
            spent_to_date=1_000_000,
            today=today,
            period_start=START,
            period_end=END,
            history=history,
            history_days=20,
            transactions=50,
            require_transactions=False,
            cfg=CFG,
        )  # fmt: skip
    )
    s = spread([v for _, v in history], CFG)
    assert s > 0
    assert wide.interval_high - wide.predicted_total == pytest.approx(CFG.z * s * math.sqrt(20))
    assert wide.interval_low < wide.predicted_total < wide.interval_high
    assert wide.interval_low >= wide.spent_to_date  # spending never goes down


def test_fr_07_on_the_last_day_the_total_is_what_was_spent() -> None:
    f = ok(run(today=END, spent=2_800_000))
    assert f.predicted_total == f.interval_low == f.interval_high == 2_800_000
    assert f.curve == ()


def test_fr_07_05_curve_is_cumulative_ordered_and_ends_at_the_total() -> None:
    f = ok(run())
    assert len(f.curve) == 20 and f.curve[0].day == date(2026, 11, 11) and f.curve[-1].day == END
    assert [p.p50 for p in f.curve] == sorted(p.p50 for p in f.curve)
    assert f.curve[-1].p50 == pytest.approx(f.predicted_total)
    for p in f.curve:
        assert p.p10 <= p.p50 <= p.p90


@pytest.mark.parametrize(
    ("limit", "band"),
    [(2_000_000, "high"), (3_000_000, "high"), (3_000_001, "medium"), (3_500_000, "medium"),
     (3_500_001, "low"), (9_000_000, "low")],
)  # fmt: skip
def test_fr_07_03_exceed_band_boundaries(limit: float, band: str) -> None:
    assert exceed_band(limit, p50=3_000_000, p90=3_500_000) == band


def test_fr_07_run_rate_helper_edges() -> None:
    assert run_rate_remaining(100, 0, 5) == 0 and run_rate_remaining(100, 5, 0) == 0
    assert run_rate_remaining(100, 4, 2) == 50


@settings(max_examples=200, deadline=None)
@given(
    spent=st.integers(0, 50_000_000),
    day=st.integers(1, 30),
    history_days=st.integers(14, 120),
    daily=st.lists(st.integers(0, 1_000_000), min_size=14, max_size=120),
)
def test_fr_07_02_forecast_invariants(
    spent: int, day: int, history_days: int, daily: list[int]
) -> None:
    today = START + timedelta(days=day - 1)
    series = [(today - timedelta(days=len(daily) - 1 - i), float(v)) for i, v in enumerate(daily)]
    f = forecast(
        spent_to_date=float(spent), today=today, period_start=START, period_end=END,
        history=series, history_days=max(history_days, len(daily)), transactions=999,
        require_transactions=False, cfg=CFG,
    )  # fmt: skip
    assert isinstance(f, Forecast)
    assert f.spent_to_date <= f.interval_low <= f.predicted_total <= f.interval_high
    assert f.predicted_remaining >= 0 and f.predicted_total >= spent
    assert all(
        math.isfinite(x) for x in (f.predicted_total, f.interval_high, f.baseline_prediction)
    )
    assert len(f.curve) == (END - today).days
    for a, b in zip(f.curve, f.curve[1:], strict=False):
        assert a.p50 <= b.p50 + 1e-6 and a.day < b.day


def test_fr_21_04_directional_higher_spend_to_date_never_lowers_the_p50() -> None:
    """PRD 21.4: with the same history, more spending so far does not decrease the P50."""
    totals = [ok(run(spent=spent)).predicted_total for spent in (500_000, 1_000_000, 2_000_000)]
    assert totals == sorted(totals)
