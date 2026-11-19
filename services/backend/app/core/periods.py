"""Budget period arithmetic in the user's local calendar (PRD 4.5). Pure functions."""

from __future__ import annotations

import datetime as dt


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
