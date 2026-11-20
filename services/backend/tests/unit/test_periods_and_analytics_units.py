"""Budget periods (PRD 4.5) and the pure parts of analytics (7.4): no database needed."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.core.errors import ProblemError
from app.core.periods import PeriodBounds, next_period_start, period_bounds, period_start
from app.services.analytics import (
    MAX_CUSTOM_DAYS,
    AnalyticsService,
    change,
    money,
    percent,
)
from hypothesis import given, settings
from hypothesis import strategies as st

D = dt.date
NOV_20 = D(2026, 11, 20)


# --- period boundaries ---------------------------------------------------------------------------
def test_period_boundaries_start_day_25_across_year_end() -> None:
    assert period_bounds(D(2026, 1, 10), 25) == PeriodBounds(D(2025, 12, 25), D(2026, 1, 24))
    assert period_bounds(D(2025, 12, 25), 25) == PeriodBounds(D(2025, 12, 25), D(2026, 1, 24))
    assert period_bounds(D(2025, 12, 24), 25) == PeriodBounds(D(2025, 11, 25), D(2025, 12, 24))
    assert period_bounds(D(2026, 1, 24), 25).period_id == "2025-12-25"
    assert period_bounds(D(2026, 1, 25), 25).period_id == "2026-01-25"


def test_period_bounds_start_day_1_handles_short_and_leap_februaries() -> None:
    assert period_bounds(D(2026, 2, 10), 1) == PeriodBounds(D(2026, 2, 1), D(2026, 2, 28))
    assert period_bounds(D(2028, 2, 10), 1).end == D(2028, 2, 29)
    assert period_bounds(D(2026, 2, 10), 1).days == 28
    assert period_bounds(D(2026, 12, 31), 1) == PeriodBounds(D(2026, 12, 1), D(2026, 12, 31))


def test_period_start_day_change_applies_next_period() -> None:
    old, new, effective = 1, 15, D(2026, 12, 1)
    # The current period keeps its boundaries (it ends the day before the change applies).
    assert period_bounds(D(2026, 11, 20), old, new, effective) == PeriodBounds(
        D(2026, 11, 1), D(2026, 11, 30)
    )
    # The first new period starts on the effective date and runs to the next new start day.
    assert period_bounds(D(2026, 12, 1), old, new, effective) == PeriodBounds(
        D(2026, 12, 1), D(2026, 12, 14)
    )
    assert period_bounds(D(2026, 12, 15), old, new, effective) == PeriodBounds(
        D(2026, 12, 15), D(2027, 1, 14)
    )
    # Mid-period change on a start day that moves earlier: still no gap, no overlap.
    assert period_bounds(D(2026, 11, 28), 25, 5, D(2026, 12, 25)) == PeriodBounds(
        D(2026, 11, 25), D(2026, 12, 24)
    )
    assert period_bounds(D(2026, 12, 30), 25, 5, D(2026, 12, 25)) == PeriodBounds(
        D(2026, 12, 25), D(2027, 1, 4)
    )


@given(
    start_day=st.integers(1, 28),
    pending_day=st.integers(1, 28),
    today=st.dates(D(2024, 1, 1), D(2028, 12, 31)),
)
@settings(max_examples=150, deadline=None)
def test_periods_tile_the_calendar_with_no_gap_and_no_overlap(
    start_day: int, pending_day: int, today: dt.date
) -> None:
    effective = next_period_start(today, start_day)
    args = (start_day, pending_day, effective)
    cursor = period_start(today, start_day) - dt.timedelta(days=40)
    for _ in range(200):
        bounds = period_bounds(cursor, *args)
        assert bounds.start <= cursor <= bounds.end and bounds.days >= 1
        assert period_bounds(bounds.start, *args) == bounds  # every day of a period agrees
        assert period_bounds(bounds.end, *args) == bounds
        following = period_bounds(bounds.end + dt.timedelta(days=1), *args)
        assert following.start == bounds.end + dt.timedelta(days=1)
        cursor = bounds.end + dt.timedelta(days=1)


# --- numbers -------------------------------------------------------------------------------------
def test_percent_rounds_half_up_to_one_decimal_and_handles_zero() -> None:
    assert percent(Decimal("1"), Decimal("8")) == Decimal("12.5")
    assert percent(Decimal("1"), Decimal("16")) == Decimal("6.3")  # 6.25 -> half up
    assert percent(Decimal("1"), Decimal("3")) == Decimal("33.3")
    assert percent(Decimal("5"), Decimal("0")) is None
    assert percent(Decimal("-5"), Decimal("10")) == Decimal("-50.0")


def test_fr_04_07_change_is_null_when_previous_is_zero() -> None:
    assert change(Decimal("100"), Decimal("0")) is None
    assert change(Decimal("0"), Decimal("0")) is None
    assert change(Decimal("150"), Decimal("100")) == Decimal("50.0")
    assert change(Decimal("50"), Decimal("100")) == Decimal("-50.0")
    assert change(Decimal("0"), Decimal("100")) == Decimal("-100.0")


def test_fr_04_07_change_of_a_negative_base_keeps_the_direction() -> None:
    # Net going from -50,000 to +100,000 is an increase: +300%, not -300%.
    assert change(Decimal("100000"), Decimal("-50000")) == Decimal("300.0")
    assert change(Decimal("-100000"), Decimal("-50000")) == Decimal("-100.0")


def test_money_has_two_decimals() -> None:
    assert str(money(Decimal("5"))) == "5.00"
    assert str(money(Decimal("0.005"))) == "0.01"
    assert str(money(Decimal("1E+3"))) == "1000.00"


# --- range resolution ----------------------------------------------------------------------------
def service(
    today: dt.date = NOV_20,
    start_day: int = 1,
    tz: str = "Asia/Jakarta",
    pending: tuple[int, dt.date] | None = None,
) -> AnalyticsService:
    user = SimpleNamespace(
        id="u",
        timezone=tz,
        budget_period_start_day=start_day,
        pending_period_start_day=pending[0] if pending else None,
        pending_period_start_effective=pending[1] if pending else None,
        opening_balance=Decimal("0"),
    )
    now = dt.datetime.combine(today, dt.time(12, 0), tzinfo=dt.UTC)
    return AnalyticsService(None, user, now)  # type: ignore[arg-type]


def test_fr_04_10_ranges_follow_the_users_budget_period() -> None:
    s = service(start_day=25, today=D(2026, 1, 10))
    cur = s.window("current_period", None, None)
    assert (cur.start, cur.end, cur.previous) == (
        D(2025, 12, 25),
        D(2026, 1, 24),
        (D(2025, 11, 25), D(2025, 12, 24)),
    )
    prev = s.window("previous_period", None, None)
    assert (prev.start, prev.end, prev.previous) == (
        D(2025, 11, 25),
        D(2025, 12, 24),
        (D(2025, 10, 25), D(2025, 11, 24)),
    )
    three = s.window("last_3_periods", None, None)
    assert (three.start, three.end) == (D(2025, 9, 25), D(2025, 12, 24))
    assert three.previous == (D(2025, 6, 25), D(2025, 9, 24))
    assert (cur.single_period, prev.single_period, three.single_period) == (True, True, False)


def test_fr_04_10_today_is_taken_in_the_users_time_zone() -> None:
    # 20:00Z on Nov 30 is already Dec 1 in Jakarta: a new period has started.
    user_now = dt.datetime(2026, 11, 30, 20, 0, tzinfo=dt.UTC)
    s = service()
    s.now, s.today = user_now, user_now.astimezone(s.tz).date()
    assert s.window("current_period", None, None).start == D(2026, 12, 1)


def test_fr_04_10_custom_range_rules() -> None:
    s = service()
    ok = s.window("custom", D(2026, 1, 1), D(2026, 1, 1))
    assert (ok.days, ok.previous) == (1, (D(2025, 12, 31), D(2025, 12, 31)))
    longest = s.window(
        "custom", D(2025, 1, 1), D(2025, 1, 1) + dt.timedelta(days=MAX_CUSTOM_DAYS - 1)
    )
    assert longest.days == MAX_CUSTOM_DAYS
    for args in (
        (None, None),
        (D(2026, 1, 1), None),
        (D(2026, 2, 1), D(2026, 1, 1)),
        (D(2025, 1, 1), D(2025, 1, 1) + dt.timedelta(days=MAX_CUSTOM_DAYS)),
    ):
        with pytest.raises(ProblemError) as err:
            s.window("custom", *args)
        assert err.value.status == 422
    with pytest.raises(ProblemError):
        s.window("current_period", D(2026, 1, 1), D(2026, 1, 2))


def test_fr_04_10_granularity_is_automatic_by_length() -> None:
    auto = AnalyticsService.auto_granularity
    assert [auto(n) for n in (1, 62, 63, 183, 184, 366)] == [
        "day", "day", "week", "week", "month", "month",
    ]  # fmt: skip


def test_days_elapsed_counts_today_and_clamps() -> None:
    s = service(today=D(2026, 11, 20))
    info = s.period_info(s.window("current_period", None, None))
    assert (info.days_elapsed, info.days_in_period, info.in_progress) == (20, 30, True)
    last_day = service(today=D(2026, 11, 30))
    info = last_day.period_info(last_day.window("current_period", None, None))
    assert (info.days_elapsed, info.in_progress) == (30, True)
    past = s.period_info(s.window("previous_period", None, None))
    assert (past.days_elapsed, past.in_progress) == (31, False)
    future = s.period_info(s.window("custom", D(2027, 1, 1), D(2027, 1, 10)))
    assert (future.days_elapsed, future.in_progress) == (0, False)


# --- buckets -------------------------------------------------------------------------------------
@given(
    start=st.dates(D(2025, 1, 1), D(2026, 12, 31)),
    length=st.integers(1, 366),
    start_day=st.integers(1, 28),
    granularity=st.sampled_from(["day", "week", "month"]),
)
@settings(max_examples=120, deadline=None)
def test_fr_04_06_buckets_tile_the_range_exactly(
    start: dt.date, length: int, start_day: int, granularity: str
) -> None:
    s = service(start_day=start_day)
    window = s.window("custom", start, start + dt.timedelta(days=length - 1))
    buckets = s.buckets(window, granularity)  # type: ignore[arg-type]
    assert buckets[0][0] == window.start and buckets[-1][1] == window.end
    for (_, end), (next_start, _) in zip(buckets, buckets[1:], strict=False):
        assert next_start == end + dt.timedelta(days=1)  # no gap, no overlap
    assert all(a <= b for a, b in buckets)
    if granularity == "day":
        assert len(buckets) == length
    if granularity == "week":
        assert all(b.weekday() == 6 or b == window.end for _, b in buckets)  # Sunday or the end
        assert all(a.weekday() == 0 or a == window.start for a, _ in buckets)  # Monday or the start


def test_fr_04_06_month_buckets_are_budget_periods_not_calendar_months() -> None:
    s = service(start_day=25)
    window = s.window("custom", D(2025, 11, 10), D(2026, 2, 5))
    assert s.buckets(window, "month") == [
        (D(2025, 11, 10), D(2025, 11, 24)),  # clipped to the range start
        (D(2025, 11, 25), D(2025, 12, 24)),
        (D(2025, 12, 25), D(2026, 1, 24)),
        (D(2026, 1, 25), D(2026, 2, 5)),  # clipped to the range end
    ]
