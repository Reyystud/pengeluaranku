"""Period-end expense forecast service (PRD 7.7): compute, cache, lazy refresh, budget bands.

The arithmetic is ``ml.forecasting`` (run-rate below 60 days of history, seasonal naive from 60);
this module feeds it SQL history, stores the result in ``forecasts`` and applies the cache rule
of FR-07.07. Nothing here logs amounts (PRD 17.3).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import validation_problem
from app.core.ids import new_uuid7
from app.core.periods import PeriodBounds
from app.models import Category, User
from app.models import Forecast as StoredForecast
from app.models.base import utcnow
from app.repositories import BudgetRepository, CategoryRepository
from app.repositories.analytics import bounds_to_utc
from app.repositories.forecasts import ForecastRepository
from app.schemas.budgets import BudgetPeriod
from app.schemas.forecasts import (
    CurvePointOut,
    ForecastBudget,
    ForecastOut,
    ForecastUnavailable,
)
from app.schemas.transactions import CategoryRef
from app.services.analytics import AnalyticsService
from ml.forecasting import Forecast as Computed
from ml.forecasting import Unavailable, exceed_band, forecast, load_forecast_config

CENT = Decimal("0.01")
_DAY = dt.timedelta(days=1)


def to_money(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


class ForecastService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.cfg = load_forecast_config()
        self.repo = ForecastRepository(session)
        self.budgets = BudgetRepository(session)
        self.analytics = AnalyticsService(session, user, now)
        self.now = self.analytics.now
        self.today = self.analytics.today
        self.tz = ZoneInfo(user.timezone)
        cats = CategoryRepository(session).list()
        self.by_slug = {c.slug: c for c in cats}
        self.by_id = {c.id: c for c in cats}

    # -- category lookup -----------------------------------------------------------------------
    def category_for(self, slug: str | None) -> Category | None:
        if slug is None:
            return None
        category = self.by_slug.get(slug.strip().lower())
        if category is None:
            raise validation_problem("category", "UNKNOWN_CATEGORY", "Unknown category.")
        if category.transaction_type != "expense":
            raise validation_problem(
                "category", "CATEGORY_TYPE_MISMATCH", "Forecasts cover expense categories only."
            )
        return category

    # -- compute -------------------------------------------------------------------------------
    def compute(self, period: PeriodBounds, category: Category | None) -> Computed | Unavailable:
        user_id = self.user.id
        category_id = category.id if category else None
        first = self.repo.first_local_date(user_id, self.user.timezone)
        if first is None:
            return Unavailable(self.cfg.min_history_days, 0)
        history_days = (self.today - first).days + 1
        lo, hi = bounds_to_utc(period.start, self.today, self.tz)
        spent = self.repo.spent_between(user_id, lo, hi, category_id)
        window_start = max(first, self.today - dt.timedelta(days=self.cfg.spread_window_days - 1))
        w_lo, w_hi = bounds_to_utc(window_start, self.today, self.tz)
        history = self.repo.daily_spend(
            user_id, self.user.timezone, window_start, self.today, w_lo, w_hi, category_id
        )
        return forecast(
            spent_to_date=float(spent),
            today=self.today,
            period_start=period.start,
            period_end=period.end,
            history=history,
            history_days=history_days,
            transactions=self.repo.expense_count(user_id, category_id),
            require_transactions=category is not None,
            cfg=self.cfg,
        )

    def _store(
        self, period: PeriodBounds, category: Category | None, f: Computed
    ) -> StoredForecast:
        row = StoredForecast(
            id=new_uuid7(),
            period_id=period.start,
            category_id=category.id if category else None,
            as_of=self.now,
            spent_to_date=to_money(f.spent_to_date),
            predicted_total=to_money(f.predicted_total),
            interval_low=to_money(f.interval_low),
            interval_high=to_money(f.interval_high),
            baseline_prediction=to_money(f.baseline_prediction),
            expected_recurring_remaining=to_money(f.expected_recurring_remaining),
            method=f.method,
            history_level=f.history_level,
            daily_curve=[
                {
                    "date": p.day.isoformat(),
                    "p10": str(to_money(p.p10)),
                    "p50": str(to_money(p.p50)),
                    "p90": str(to_money(p.p90)),
                }
                for p in f.curve
            ],
            model_version=self.cfg.version,
            created_at=utcnow(),
        )
        self.repo.add(self.user.id, row)
        self.session.flush()
        self.repo.prune(self.user.id, period.start, row.category_id, self.cfg.keep_per_series)
        return row

    def refresh(
        self, period: PeriodBounds, category: Category | None
    ) -> StoredForecast | Unavailable:
        """Compute and store a new forecast (daily batch, or a stale cache)."""
        result = self.compute(period, category)
        if isinstance(result, Unavailable):
            return result
        return self._store(period, category, result)

    def refresh_all(self) -> int:
        """The daily batch for one user (T-37): overall plus every eligible category."""
        period = self.analytics.period_of(self.today)
        count = 0
        for category in (
            None,
            *(c for c in self.by_id.values() if c.transaction_type == "expense"),
        ):
            if not isinstance(self.refresh(period, category), Unavailable):
                count += 1
        return count

    # -- cache rule (FR-07.07) -----------------------------------------------------------------
    def _is_stale(self, row: StoredForecast) -> bool:
        if row.as_of.astimezone(self.tz).date() != self.today:
            return True  # the period moved a day: the curve and the remaining days changed
        if self.now - row.as_of < dt.timedelta(hours=self.cfg.cache_max_age_hours):
            return False
        return self.repo.changed_since(self.user.id, row.as_of)

    def current(
        self, category: Category | None
    ) -> tuple[PeriodBounds, StoredForecast | Unavailable]:
        period = self.analytics.period_of(self.today)
        category_id = category.id if category else None
        cached = self.repo.latest(self.user.id, period.start, category_id)
        if cached is not None and not self._is_stale(cached):
            return period, cached
        return period, self.refresh(period, category)

    # -- API shape -----------------------------------------------------------------------------
    def get(self, category_slug: str | None) -> ForecastOut | ForecastUnavailable:
        category = self.category_for(category_slug)
        period, result = self.current(category)
        if isinstance(result, Unavailable):
            return ForecastUnavailable(
                days_needed=result.days_needed, transactions_needed=result.transactions_needed
            )
        return self._out(period, category, result)

    def _out(
        self, period: PeriodBounds, category: Category | None, row: StoredForecast
    ) -> ForecastOut:
        remaining = row.predicted_total - row.spent_to_date
        budget = self.budgets.get_for_category(self.user.id, category.id if category else None)
        out_budget = None
        if budget is not None:
            band = exceed_band(
                float(budget.limit_amount), float(row.predicted_total), float(row.interval_high)
            )
            out_budget = ForecastBudget(
                limit_amount=str(to_money(budget.limit_amount)),
                predicted_over_budget=str(to_money(row.predicted_total - budget.limit_amount)),
                exceed_band=band,
            )
        balance = None
        if category is None:  # FR-07.04: no expected income until recurring detection (T-30)
            balance = str(to_money(self.analytics.current_balance() - remaining))
        elapsed = min(max((self.today - period.start).days + 1, 0), period.days)
        return ForecastOut(
            period=BudgetPeriod(
                start=period.start,
                end=period.end,
                period_id=period.period_id,
                days_in_period=period.days,
                days_elapsed=elapsed,
            ),
            category=CategoryRef(id=category.id, slug=category.slug, name=category.name)
            if category
            else None,
            spent_to_date=str(to_money(row.spent_to_date)),
            predicted_total=str(to_money(row.predicted_total)),
            interval_low=str(to_money(row.interval_low)),
            interval_high=str(to_money(row.interval_high)),
            predicted_remaining=str(to_money(remaining)),
            expected_recurring_remaining=str(to_money(row.expected_recurring_remaining)),
            baseline_prediction=str(to_money(row.baseline_prediction)),
            method=row.method,  # type: ignore[arg-type]
            history_level=row.history_level,  # type: ignore[arg-type]
            model_version=row.model_version,
            generated_at=row.as_of,
            budget=out_budget,
            estimated_period_end_balance=balance,
            daily_curve=[CurvePointOut.model_validate(p) for p in row.daily_curve],
        )

    # -- budget projection (FR-05.07) ----------------------------------------------------------
    def projected(self, category_id: uuid.UUID | None, limit: Decimal) -> str | None:
        """``on_track`` / ``may_exceed`` (band medium or high), None without a forecast."""
        category = self.by_id.get(category_id) if category_id else None
        _, result = self.current(category)
        if isinstance(result, Unavailable):
            return None
        band = exceed_band(float(limit), float(result.predicted_total), float(result.interval_high))
        return "on_track" if band == "low" else "may_exceed"
