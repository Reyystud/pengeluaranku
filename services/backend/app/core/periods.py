"""Budget period arithmetic in the user's local calendar (PRD 4.5). Pure functions."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

_DAY = dt.timedelta(days=1)


def _month_start(year: int, month: int, start_day: int) -> dt.date:
    return dt.date(year, month, start_day)


def period_start(day: dt.date, start_day: int) -> dt.date:
    """Start of the period containing ``day``: latest date <= day whose day-of-month is start."""
    if day.day >= start_day:
        return _month_start(day.year, day.month, start_day)
    year, month = (day.year - 1, 12) if day.month == 1 else (day.year, day.month - 1)
    return _month_start(year, month, start_day)


def next_period_start(day: dt.date, start_day: int) -> dt.date:
    """Start of the period after the one containing ``day``."""
    current = period_start(day, start_day)
    year, month = (
        (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    )
    return _month_start(year, month, start_day)


@dataclass(frozen=True)
class PeriodBounds:
    """One budget period: ``start`` and ``end`` are both inclusive local dates (PRD 4.5)."""

    start: dt.date
    end: dt.date

    @property
    def period_id(self) -> str:
        return self.start.isoformat()

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def period_bounds(
    day: dt.date,
    start_day: int,
    pending_day: int | None = None,
    pending_effective: dt.date | None = None,
) -> PeriodBounds:
    """Boundaries of the period containing ``day``.

    A start-day change takes effect from the next period (4.5): the current period keeps its
    boundaries and ends the day before ``pending_effective``. From that date on the new start day
    applies; the first new period begins on ``pending_effective`` itself, so it may be shorter or
    longer than usual (a transition period) and no day is ever left out or counted twice.
    """
    if pending_day is None or pending_effective is None:
        return PeriodBounds(period_start(day, start_day), next_period_start(day, start_day) - _DAY)
    if day < pending_effective:
        start = period_start(day, start_day)
        end = min(next_period_start(day, start_day), pending_effective) - _DAY
        return PeriodBounds(start, end)
    start = max(period_start(day, pending_day), pending_effective)
    return PeriodBounds(start, next_period_start(day, pending_day) - _DAY)
