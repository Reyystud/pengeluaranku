"""Insights engine (PRD 7.9, FR-09): gather facts, apply the rules, store the result.

Deterministic and rule-based: the same ledger gives the same insights, and each stored insight
carries the evidence it was computed from. ``refresh`` is idempotent (one row per rule, period and
subject) and is what both the daily job and ``POST /intelligence/insights/refresh`` call.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models import Insight, User
from app.repositories.analytics import AnalyticsRepository, bounds_to_utc
from app.repositories.budgets import BudgetRepository
from app.repositories.forecasts import ForecastRepository
from app.repositories.insights import InsightRepository
from app.repositories.users import CategoryRepository
from app.schemas.insights import InsightList, InsightOut, RefreshOut
from app.services.analytics import AnalyticsService
from app.services.forecasts import ForecastService
from app.services.insight_config import InsightConfig, load_insight_config
from app.services.insight_rules import (
    BudgetPace,
    CategoryDelta,
    Facts,
    PriceChange,
    WeekendFacts,
    evaluate,
)
from app.services.recurring import RecurringService
from ml.forecasting import Unavailable, exceed_band
from ml.recurring import amount_change

_DAY = dt.timedelta(days=1)
LIVE_RECURRING = ("active", "user_confirmed")


class InsightService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.cfg: InsightConfig = load_insight_config()
        self.tz = ZoneInfo(user.timezone)
        self.now = now or dt.datetime.now(dt.UTC)
        self.today = self.now.astimezone(self.tz).date()
        self.repo = InsightRepository(session)
        self.analytics_repo = AnalyticsRepository(session)
        self.analytics = AnalyticsService(session, user, self.now)
        self.period = self.analytics.period_of(self.today)

    # -- facts ---------------------------------------------------------------------------------
    def gather(self) -> Facts:
        user_id = self.user.id
        period = self.period
        previous = self.analytics.period_of(period.start - _DAY)
        elapsed = (self.today - period.start).days + 1
        first = ForecastRepository(self.session).first_local_date(user_id, self.user.timezone)
        previous_complete = first is not None and first <= previous.start

        lo, hi = bounds_to_utc(period.start, self.today, self.tz)
        prev_same_end = min(previous.start + dt.timedelta(days=elapsed - 1), previous.end)
        plo, phi = bounds_to_utc(previous.start, prev_same_end, self.tz)
        current_rows = {r.slug: r for r in self.analytics_repo.category_breakdown(user_id, lo, hi)}
        previous_rows = {
            r.slug: r for r in self.analytics_repo.category_breakdown(user_id, plo, phi)
        }
        categories = [
            CategoryDelta(
                slug,
                (current_rows.get(slug) or previous_rows[slug]).name,
                current_rows[slug].amount if slug in current_rows else Decimal(0),
                previous_rows[slug].amount if slug in previous_rows else Decimal(0),
            )
            for slug in sorted(set(current_rows) | set(previous_rows))
        ]

        period_flow = self.analytics_repo.flows_between(user_id, lo, hi)
        small_n, small_sum = self.repo.small_purchases(
            user_id, lo, hi, self.cfg.number("INS-06", "below")
        )
        top = self.analytics_repo.top_merchants(user_id, lo, hi, 1)
        top_merchant = (
            (top[0].merchant_key, top[0].display, top[0].amount, top[0].count) if top else None
        )

        prev_lo, prev_hi = bounds_to_utc(previous.start, previous.end, self.tz)
        prev_flow = self.analytics_repo.flows_between(user_id, prev_lo, prev_hi)

        recurring = RecurringService(self.session, self.user, self.now)
        series = [
            s
            for s in recurring.repo.all(user_id)
            if s.transaction_type == "expense" and recurring.live_status(s) in LIVE_RECURRING
        ]
        recent = recurring.repo.recent_amounts(user_id, [s.id for s in series], 4)
        price_changes = []
        for s in series:
            change = amount_change(recent.get(s.id, []), recurring.cfg)
            if change is not None:
                price_changes.append(
                    PriceChange(
                        s.merchant_key,
                        s.merchant_display,
                        change.previous_amount,
                        change.latest_amount,
                    )
                )

        return Facts(
            period_start=period.start,
            period_end=period.end,
            previous_start=previous.start,
            previous_end=previous.end,
            elapsed_days=elapsed,
            previous_complete=previous_complete,
            categories=categories,
            weekend=self._weekend(first),
            recurring_monthly=sum((recurring.monthly_amount(s) for s in series), Decimal(0)),
            recurring_count=len(series),
            average_monthly_expenses=self._average_monthly(previous, first),
            budgets=self._budget_pace(),
            top_merchant=top_merchant,
            period_expenses=period_flow.expenses,
            small_count=small_n,
            small_sum=small_sum,
            previous_income=prev_flow.income,
            previous_expenses=prev_flow.expenses,
            price_changes=price_changes,
            review_queue=self.analytics_repo.review_queue_count(user_id),
        )

    def _weekend(self, first: dt.date | None) -> WeekendFacts | None:
        weeks = int(self.cfg.number("INS-02", "weeks"))
        end = self.today - _DAY  # complete days only
        start = max(end - dt.timedelta(days=weeks * 7 - 1), first or end)
        if first is None or start > end:
            return None
        days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        rows = self.analytics_repo.expense_buckets(self.user.id, self.tz, [(d, d) for d in days])
        weekend_total = weekday_total = Decimal(0)
        weekend_days = weekday_days = 0
        weekends: set[tuple[int, int]] = set()
        for day, row in zip(days, rows, strict=True):
            if day.weekday() >= 5:
                weekend_total += row.expenses
                weekend_days += 1
                if row.expenses > 0:
                    iso = day.isocalendar()
                    weekends.add((iso.year, iso.week))
            else:
                weekday_total += row.expenses
                weekday_days += 1
        return WeekendFacts(weekend_total, weekend_days, weekday_total, weekday_days, len(weekends))

    def _average_monthly(self, previous: object, first: dt.date | None) -> Decimal | None:
        """Mean expenses over up to N complete periods that started after the first transaction."""
        count = int(self.cfg.number("INS-03", "periods"))
        totals: list[Decimal] = []
        bounds = self.analytics.period_of(self.period.start - _DAY)
        for _ in range(count):
            if first is None or bounds.start < first:
                break
            lo, hi = bounds_to_utc(bounds.start, bounds.end, self.tz)
            totals.append(self.analytics_repo.flows_between(self.user.id, lo, hi).expenses)
            bounds = self.analytics.period_of(bounds.start - _DAY)
        return sum(totals, Decimal(0)) / len(totals) if totals else None

    def _budget_pace(self) -> list[BudgetPace]:
        forecasts = ForecastService(self.session, self.user, self.now)
        by_id = {c.id: c for c in CategoryRepository(self.session).list()}
        out = []
        for budget in BudgetRepository(self.session).list_all(self.user.id):
            category = by_id.get(budget.category_id) if budget.category_id else None
            _, result = forecasts.current(category)
            if isinstance(result, Unavailable):
                continue
            band = exceed_band(
                float(budget.limit_amount),
                float(result.predicted_total),
                float(result.interval_high),
            )
            out.append(
                BudgetPace(
                    category.slug if category else None,
                    category.name if category else "Overall",
                    Decimal(budget.limit_amount),
                    Decimal(result.predicted_total),
                    band,
                )
            )
        return out

    # -- use cases -----------------------------------------------------------------------------
    def refresh(self) -> RefreshOut:
        """Recompute this user's insights for the current period (FR-09.01)."""
        candidates = evaluate(self.gather(), self.cfg)
        created = self.repo.upsert(self.user.id, self.period.start, candidates)
        removed = self.repo.delete_stale(
            self.user.id, self.period.start, {(c.rule_id, c.subject_key) for c in candidates}
        )
        total = len(self.repo.page(self.user.id, self.period.start, True, 1000))
        return RefreshOut(
            period_id=self.period.start, created=created, removed=removed, total=total
        )

    def listing(self, period_id: dt.date | None, include_dismissed: bool) -> InsightList:
        wanted = period_id or self.period.start
        rows = self.repo.page(self.user.id, wanted, include_dismissed, 200)
        return InsightList(period_id=wanted, items=[self._out(r) for r in rows])

    def top(self, limit: int | None = None) -> list[InsightOut]:
        """FR-09.05: warning before positive before info, then by magnitude."""
        rows = self.repo.page(
            self.user.id, self.period.start, False, limit or self.cfg.dashboard_top
        )
        return [self._out(r) for r in rows]

    def dismiss(self, insight_id: uuid.UUID) -> InsightOut:
        row = self.repo.dismiss(self.user.id, insight_id)
        if row is None:
            raise not_found()
        return self._out(row)

    @staticmethod
    def _out(row: Insight) -> InsightOut:
        return InsightOut(
            id=row.id,
            rule_id=row.rule_id,
            rule_version=row.rule_version,
            period_id=row.period_id,
            subject_key=row.subject_key,
            severity=row.severity,  # type: ignore[arg-type]
            priority=f"{Decimal(row.priority):.4f}",
            title=row.title,
            message=row.message,
            message_key=row.message_key,
            message_params=row.message_params,
            evidence=row.evidence,
            dismissed_at=row.dismissed_at,
            created_at=row.created_at,
        )
