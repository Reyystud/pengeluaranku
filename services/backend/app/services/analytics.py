"""Dashboard analytics (PRD 7.4). All sums come from SQL; this module resolves ranges and shapes.

Time rules (4.2, 4.5): every date is the user's local date; a "month" is the user's budget period,
never the calendar month; weeks start on Monday.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import validation_problem
from app.core.periods import PeriodBounds, period_bounds
from app.models import User
from app.repositories.analytics import AnalyticsRepository, Flow, bounds_to_utc
from app.schemas.analytics import (
    CategoriesOut,
    CategoryItem,
    Changes,
    Comparison,
    Figures,
    Granularity,
    MerchantItem,
    MerchantsOut,
    MethodItem,
    MethodsOut,
    PeriodInfo,
    RangeName,
    SummaryOut,
    TrendPoint,
    TrendsOut,
)

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ZERO = Decimal("0.00")
MAX_CUSTOM_DAYS = 366
_DAY = dt.timedelta(days=1)


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """``numerator / denominator`` as a percent with one decimal (ROUND_HALF_UP), null if /0."""
    if denominator == 0:
        return None
    return (numerator * 100 / denominator).quantize(TENTH, rounding=ROUND_HALF_UP)


def change(current: Decimal, previous: Decimal) -> Decimal | None:
    """FR-04.07: (cur - prev) / prev in percent, one decimal; null when prev is 0.

    The divisor is ``abs(prev)``: identical to the PRD formula for income and expenses (never
    negative), and it keeps the sign meaningful for net cash flow, which can be negative (going
    from -50,000 to +100,000 is an increase, not a -300% change).
    """
    if previous == 0:
        return None
    return ((current - previous) * 100 / abs(previous)).quantize(TENTH, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Window:
    """A resolved range: inclusive local dates plus its comparison window."""

    name: RangeName
    start: dt.date
    end: dt.date
    previous: tuple[dt.date, dt.date]
    single_period: bool  # exactly one budget period (budget pace applies)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class AnalyticsService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.user = user
        self.repo = AnalyticsRepository(session)
        self.tz = ZoneInfo(user.timezone)
        self.now = now or dt.datetime.now(dt.UTC)
        self.today = self.now.astimezone(self.tz).date()

    def period_of(self, day: dt.date) -> PeriodBounds:
        """The budget period containing ``day`` (honours a pending start-day change)."""
        return self._bounds(day)

    # -- ranges (FR-04.10) ---------------------------------------------------------------------
    def _bounds(self, day: dt.date) -> PeriodBounds:
        u = self.user
        return period_bounds(
            day,
            u.budget_period_start_day,
            u.pending_period_start_day,
            u.pending_period_start_effective,
        )

    def window(self, name: RangeName, date_from: dt.date | None, date_to: dt.date | None) -> Window:
        if name != "custom" and (date_from is not None or date_to is not None):
            raise validation_problem(
                "date_from", "INVALID_VALUE", "date_from and date_to only apply to range=custom."
            )
        if name == "current_period":
            cur = self._bounds(self.today)
            prev = self._bounds(cur.start - _DAY)
            return Window(name, cur.start, cur.end, (prev.start, prev.end), True)
        if name == "previous_period":
            cur = self._bounds(self._bounds(self.today).start - _DAY)
            prev = self._bounds(cur.start - _DAY)
            return Window(name, cur.start, cur.end, (prev.start, prev.end), True)
        if name == "last_3_periods":
            # The three most recent completed periods; compared with the three before them.
            newest = self._bounds(self._bounds(self.today).start - _DAY)
            middle = self._bounds(newest.start - _DAY)
            oldest = self._bounds(middle.start - _DAY)
            before_newest = self._bounds(oldest.start - _DAY)
            before_middle = self._bounds(before_newest.start - _DAY)
            before_oldest = self._bounds(before_middle.start - _DAY)
            return Window(
                name, oldest.start, newest.end, (before_oldest.start, before_newest.end), False
            )
        if date_from is None or date_to is None:
            raise validation_problem(
                "date_from", "REQUIRED", "range=custom needs date_from and date_to."
            )
        if date_from > date_to:
            raise validation_problem("date_from", "INVALID_RANGE", "date_from is after date_to.")
        length = (date_to - date_from).days + 1
        if length > MAX_CUSTOM_DAYS:
            raise validation_problem(
                "date_to", "RANGE_TOO_LONG", f"A custom range is at most {MAX_CUSTOM_DAYS} days."
            )
        prev_end = date_from - _DAY
        return Window(name, date_from, date_to, (prev_end - (length - 1) * _DAY, prev_end), False)

    def _elapsed(self, w: Window) -> int:
        if self.today < w.start:
            return 0
        return (min(self.today, w.end) - w.start).days + 1

    def period_info(self, w: Window) -> PeriodInfo:
        return PeriodInfo(
            range=w.name,
            start=w.start,
            end=w.end,
            period_id=w.start.isoformat() if w.single_period else None,
            days_in_period=w.days,
            days_elapsed=self._elapsed(w),
            in_progress=w.start <= self.today <= w.end,
            timezone=self.user.timezone,
        )

    def _span(self, start: dt.date, end: dt.date) -> tuple[dt.datetime, dt.datetime]:
        return bounds_to_utc(start, end, self.tz)

    def _figures(self, start: dt.date, end: dt.date) -> tuple[Figures, Flow]:
        lo, hi = self._span(start, end)
        flow = self.repo.flows_between(self.user.id, lo, hi)
        net = flow.income - flow.expenses
        figures = Figures(
            start=start,
            end=end,
            income=money(flow.income),
            expenses=money(flow.expenses),
            net=money(net),
            savings_rate=percent(net, flow.income),
        )
        return figures, flow

    def current_balance(self) -> Decimal:
        """Opening balance plus all income minus all expenses up to now (FR-04.01)."""
        flow = self.repo.flows_until(self.user.id, self.now)
        return Decimal(self.user.opening_balance) + flow.income - flow.expenses

    # -- FR-04.01..04, FR-04.07 ----------------------------------------------------------------
    def summary(self, w: Window) -> SummaryOut:
        user_id = self.user.id
        whole, flow = self._figures(w.start, w.end)
        balance = self.current_balance()

        # An in-progress range is compared to the same number of days of the previous one.
        elapsed = self._elapsed(w)
        in_progress = w.start <= self.today <= w.end
        prev_start, prev_end = w.previous
        if in_progress:
            current, _ = self._figures(w.start, self.today)
            prev_end = min(prev_end, prev_start + (elapsed - 1) * _DAY)
            label = "vs. same point last period"
        else:
            current = whole
            label = "vs. previous period"
        previous, _ = self._figures(prev_start, prev_end)
        return SummaryOut(
            period=self.period_info(w),
            balance=money(balance),
            income=whole.income,
            expenses=whole.expenses,
            net=whole.net,
            savings_rate=whole.savings_rate,
            income_count=flow.income_count,
            expense_count=flow.expense_count,
            comparison=Comparison(
                label=label,
                current=current,
                previous=previous,
                change=Changes(
                    income=change(current.income, previous.income),
                    expenses=change(current.expenses, previous.expenses),
                    net=change(current.net, previous.net),
                ),
            ),
            review_queue_count=self.repo.review_queue_count(user_id),
        )

    # -- FR-04.05 ------------------------------------------------------------------------------
    def categories(self, w: Window) -> CategoriesOut:
        lo, hi = self._span(w.start, w.end)
        rows = self.repo.category_breakdown(self.user.id, lo, hi)
        total = sum((r.amount for r in rows), ZERO)
        return CategoriesOut(
            period=self.period_info(w),
            total_expenses=money(total),
            items=[
                CategoryItem(
                    slug=r.slug,
                    name=r.name,
                    amount=money(r.amount),
                    share=percent(r.amount, total) or Decimal("0.0"),
                    count=r.count,
                )
                for r in rows
            ],
        )

    # -- FR-04.08 ------------------------------------------------------------------------------
    def merchants(self, w: Window, limit: int) -> MerchantsOut:
        lo, hi = self._span(w.start, w.end)
        rows = self.repo.top_merchants(self.user.id, lo, hi, limit)
        return MerchantsOut(
            period=self.period_info(w),
            items=[
                MerchantItem(
                    merchant_key=r.merchant_key,
                    name=r.display,
                    amount=money(r.amount),
                    count=r.count,
                )
                for r in rows
            ],
        )

    # -- FR-04.09 ------------------------------------------------------------------------------
    def payment_methods(self, w: Window) -> MethodsOut:
        lo, hi = self._span(w.start, w.end)
        rows = self.repo.payment_methods(self.user.id, lo, hi)
        total = sum((r.amount for r in rows), ZERO)
        return MethodsOut(
            period=self.period_info(w),
            total_expenses=money(total),
            items=[
                MethodItem(
                    payment_method=r.payment_method,
                    amount=money(r.amount),
                    share=percent(r.amount, total) or Decimal("0.0"),
                    count=r.count,
                )
                for r in rows
            ],
        )

    # -- FR-04.06, FR-04.10 --------------------------------------------------------------------
    @staticmethod
    def auto_granularity(days: int) -> Granularity:
        return "day" if days <= 62 else "week" if days <= 183 else "month"

    def buckets(self, w: Window, granularity: Granularity) -> list[tuple[dt.date, dt.date]]:
        """Day, Monday-week or budget-period buckets, clipped to the window."""
        out: list[tuple[dt.date, dt.date]] = []
        cursor = w.start
        while cursor <= w.end:
            if granularity == "day":
                end = cursor
            elif granularity == "week":
                end = cursor + (6 - cursor.weekday()) * _DAY  # through Sunday
            else:
                end = self._bounds(cursor).end
            end = min(end, w.end)
            out.append((cursor, end))
            cursor = end + _DAY
        return out

    def trends(self, w: Window, granularity: Granularity | None) -> TrendsOut:
        chosen = granularity or self.auto_granularity(w.days)
        buckets = self.buckets(w, chosen)
        rows = self.repo.expense_buckets(self.user.id, self.tz, buckets)
        limit = self.repo.overall_budget_limit(self.user.id) if w.single_period else None
        series = []
        for row in rows:
            future = row.start > self.today
            pace = None
            if limit is not None:
                elapsed = (row.end - w.start).days + 1  # budget pace: limit x day_index / days
                pace = money(limit * elapsed / w.days)
            series.append(
                TrendPoint(
                    start=row.start,
                    end=row.end,
                    expenses=money(row.expenses),
                    cumulative=None if future else money(row.cumulative),
                    future=future,
                    budget_pace=pace,
                )
            )
        return TrendsOut(
            period=self.period_info(w),
            granularity=chosen,
            budget_limit=None if limit is None else money(limit),
            series=series,
        )
