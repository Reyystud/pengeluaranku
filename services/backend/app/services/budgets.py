"""Budgets: utilization, status, threshold notifications and period snapshots (PRD 7.5, 7.14).

Status is always computed from the ledger, never stored (FR-05.04). Threshold notifications are
created at most once per (budget, period, threshold) by the unique ``dedupe_key`` (FR-05.05), and
deleting a transaction never removes a past notification (FR-05.06).
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ProblemError, not_found, validation_problem
from app.core.periods import PeriodBounds
from app.models import Budget, Category, User
from app.models.base import utcnow
from app.repositories import BudgetRepository, CategoryRepository, NotificationRepository
from app.repositories.analytics import bounds_to_utc
from app.schemas.budgets import (
    BudgetCreate,
    BudgetHistory,
    BudgetHistoryItem,
    BudgetList,
    BudgetOut,
    BudgetPeriod,
    BudgetStatus,
    BudgetUpdate,
)
from app.schemas.transactions import CategoryRef
from app.services.analytics import AnalyticsService

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
HUNDRED = Decimal(100)
DEFAULT_THRESHOLDS = [80, 100]
MAX_RATIO = Decimal("999.9999")  # NUMERIC(7,4) in budget_period_snapshots


def utilization_percent(spent: Decimal, limit: Decimal) -> Decimal:
    """Exact spent / limit in percent (limit > 0 is enforced by the schema and a CHECK)."""
    return spent * HUNDRED / limit


def status_of(percent: Decimal) -> BudgetStatus:
    """FR-05.04: healthy < 50, normal < 80, warning < 100, exceeded >= 100."""
    if percent < 50:
        return "healthy"
    if percent < 80:
        return "normal"
    if percent < 100:
        return "warning"
    return "exceeded"


def one_decimal(value: Decimal) -> Decimal:
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


class BudgetService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.repo = BudgetRepository(session)
        self.notifications = NotificationRepository(session)
        self.analytics = AnalyticsService(session, user, now)
        self.tz = ZoneInfo(user.timezone)
        cats = CategoryRepository(session).list()
        self.by_id = {c.id: c for c in cats}
        self.by_slug = {c.slug: c for c in cats}

    # -- period --------------------------------------------------------------------------------
    def current_period(self) -> PeriodBounds:
        return self.analytics.period_of(self.analytics.today)

    def _spent(self, period: PeriodBounds) -> tuple[dict[uuid.UUID, Decimal], Decimal]:
        lo, hi = bounds_to_utc(period.start, period.end, self.tz)
        by_category = self.repo.spent_by_category(self.user.id, lo, hi)
        return by_category, sum(by_category.values(), Decimal(0))

    # -- shaping -------------------------------------------------------------------------------
    def _category_ref(self, budget: Budget) -> CategoryRef | None:
        if budget.category_id is None:
            return None
        c = self.by_id[budget.category_id]
        return CategoryRef(id=c.id, slug=c.slug, name=c.name)

    def _out(
        self,
        budget: Budget,
        period: PeriodBounds,
        by_category: dict[uuid.UUID, Decimal],
        total: Decimal,
    ) -> BudgetOut:
        spent = total if budget.category_id is None else by_category.get(budget.category_id, 0)
        spent = Decimal(spent)
        percent = utilization_percent(spent, budget.limit_amount)
        today = self.analytics.today
        elapsed = min(max((today - period.start).days + 1, 0), period.days)
        return BudgetOut(
            id=budget.id,
            category=self._category_ref(budget),
            limit_amount=budget.limit_amount.quantize(CENT, rounding=ROUND_HALF_UP),
            alert_thresholds=list(budget.alert_thresholds),
            spent=spent.quantize(CENT, rounding=ROUND_HALF_UP),
            remaining=(budget.limit_amount - spent).quantize(CENT, rounding=ROUND_HALF_UP),
            utilization=one_decimal(percent),
            status=status_of(percent),
            projected=None,
            period=BudgetPeriod(
                start=period.start,
                end=period.end,
                period_id=period.period_id,
                days_in_period=period.days,
                days_elapsed=elapsed,
            ),
            created_at=budget.created_at,
            updated_at=budget.updated_at,
        )

    # -- read ----------------------------------------------------------------------------------
    def list(self) -> BudgetList:
        budgets = self.repo.list_all(self.user.id)
        period = self.current_period()
        by_category, total = self._spent(period)
        items = [self._out(b, period, by_category, total) for b in budgets]
        overall = next((b for b in budgets if b.category_id is None), None)
        category_sum = sum(
            (b.limit_amount for b in budgets if b.category_id is not None), Decimal(0)
        )
        return BudgetList(
            items=items,
            category_limits_exceed_overall=overall is not None
            and category_sum > overall.limit_amount,
        )

    def get(self, budget_id: uuid.UUID) -> BudgetOut:
        budget = self.repo.require(self.user.id, budget_id)
        period = self.current_period()
        by_category, total = self._spent(period)
        return self._out(budget, period, by_category, total)

    def history(self, budget_id: uuid.UUID, limit: int) -> BudgetHistory:
        self.repo.require(self.user.id, budget_id)
        rows = self.repo.snapshots(self.user.id, budget_id, limit)
        return BudgetHistory(
            items=[
                BudgetHistoryItem(
                    period_id=r.period_id,
                    limit_amount=r.limit_amount,
                    spent=r.spent,
                    utilization=one_decimal(r.utilization * HUNDRED),
                )
                for r in rows
            ]
        )

    # -- write ---------------------------------------------------------------------------------
    def _category_for(self, ref: str | None) -> Category | None:
        if ref is None:
            return None
        key = ref.strip().lower()
        category = self.by_slug.get(key) or next(
            (c for c in self.by_id.values() if str(c.id) == key), None
        )
        if category is None:
            raise validation_problem("category", "UNKNOWN_CATEGORY", "Unknown category.")
        if category.transaction_type != "expense":  # FR-05.10 (uncategorized/transfer/income)
            raise validation_problem(
                "category", "CATEGORY_TYPE_MISMATCH", "Budgets apply to expense categories only."
            )
        return category

    def create(self, data: BudgetCreate) -> BudgetOut:
        category = self._category_for(data.category)
        category_id = category.id if category else None
        if self.repo.get_for_category(self.user.id, category_id) is not None:
            raise budget_exists()
        budget = Budget(
            category_id=category_id,
            limit_amount=data.limit_amount,
            alert_thresholds=data.alert_thresholds
            if data.alert_thresholds is not None
            else list(DEFAULT_THRESHOLDS),
        )
        try:
            with self.session.begin_nested():
                self.repo.add(self.user.id, budget)
        except IntegrityError as exc:  # a concurrent request won the unique index
            raise budget_exists() from exc
        self.evaluate()
        return self.get(budget.id)

    def update(self, budget_id: uuid.UUID, data: BudgetUpdate) -> BudgetOut:
        budget = self.repo.require(self.user.id, budget_id)
        sent = data.model_fields_set
        if "limit_amount" in sent:
            if data.limit_amount is None:
                raise validation_problem("limit_amount", "INVALID_AMOUNT", "Limit is required.")
            budget.limit_amount = data.limit_amount
        if "alert_thresholds" in sent:
            if data.alert_thresholds is None:
                raise validation_problem(
                    "alert_thresholds", "INVALID_VALUE", "Thresholds cannot be null."
                )
            budget.alert_thresholds = data.alert_thresholds
        budget.updated_at = utcnow()
        self.session.flush()
        self.evaluate()  # a lower limit or a new threshold may already be crossed
        return self.get(budget.id)

    def delete(self, budget_id: uuid.UUID) -> None:
        if not self.repo.delete(self.user.id, budget_id):
            raise not_found()

    # -- thresholds (FR-05.05, FR-05.06) ------------------------------------------------------
    def evaluate(self) -> int:
        """Create the notifications for thresholds crossed in the current period; returns how many.

        Called after every transaction write that can change spending, and by the daily job.
        """
        budgets = self.repo.list_all(self.user.id)
        if not budgets:
            return 0
        period = self.current_period()
        by_category, total = self._spent(period)
        created = 0
        for budget in budgets:
            spent = total if budget.category_id is None else by_category.get(budget.category_id, 0)
            percent = utilization_percent(Decimal(spent), budget.limit_amount)
            name = self.by_id[budget.category_id].name if budget.category_id else "Overall"
            for threshold in budget.alert_thresholds:
                if percent < threshold:
                    continue
                shown = one_decimal(percent)
                slug = self.by_id[budget.category_id].slug if budget.category_id else None
                created += self.notifications.create_once(
                    self.user.id,
                    type="budget_threshold",
                    title=f"{name} budget at {threshold}%",
                    body=(
                        f"You have used {shown}% of your {name} budget this period "
                        f"({Decimal(spent):.2f} of {budget.limit_amount:.2f})."
                    ),
                    link="/budgets",
                    payload={
                        "budget_id": str(budget.id),
                        "category": slug,
                        "period_id": period.period_id,
                        "threshold": threshold,
                        "spent": f"{Decimal(spent):.2f}",
                        "limit_amount": f"{budget.limit_amount:.2f}",
                        "utilization": str(shown),
                    },
                    dedupe_key=f"budget:{budget.id}:{period.period_id}:{threshold}",
                )
        return created

    # -- snapshots (FR-05.08) ------------------------------------------------------------------
    def snapshot_closed_period(self) -> int:
        """Write the snapshot of the period that just ended, once per budget (daily job, T-37).

        The limit stored is the one in force when the job runs, which is the first day after the
        period; a limit changed since then is not rewritten into history.
        """
        closed = self.analytics.period_of(self.current_period().start - dt.timedelta(days=1))
        budgets = self.repo.list_all(self.user.id)
        if not budgets:
            return 0
        lo, hi = bounds_to_utc(closed.start, closed.end, self.tz)
        by_category = self.repo.spent_by_category(self.user.id, lo, hi)
        total = sum(by_category.values(), Decimal(0))
        written = 0
        for budget in budgets:
            if budget.created_at.astimezone(self.tz).date() > closed.end:
                continue  # the budget did not exist during that period
            spent = total if budget.category_id is None else by_category.get(budget.category_id, 0)
            ratio = min(Decimal(spent) / budget.limit_amount, MAX_RATIO).quantize(Decimal("0.0001"))
            written += self.repo.write_snapshot(
                self.user.id,
                budget.id,
                closed.start,
                budget.limit_amount,
                Decimal(spent).quantize(CENT),
                ratio,
            )
        return written


def budget_exists() -> ProblemError:
    return ProblemError(
        409,
        "BUDGET_EXISTS",
        "Budget already exists",
        "You already have a budget for this category. Edit it instead.",
    )
