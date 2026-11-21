"""Recurring series (PRD 7.8, FR-08): detect, store, list, edit, and feed the forecast.

The rules are ``ml.recurring``; this module feeds them SQL history, stores the result in
``recurring_series`` (+ the linked transactions) and keeps what the user decided. Until the
nightly job exists (T-37), reading the list and recomputing a forecast run detection first, which
is idempotent and cheap (one query over the last 400 days). Nothing here logs merchants or
amounts (PRD 17.3).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Collection
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import validation_problem
from app.core.ids import new_uuid7
from app.models import RecurringSeries, User
from app.repositories import CategoryRepository
from app.repositories.recurring import RecurringSeriesRepository
from app.schemas.recurring import (
    AmountChangeOut,
    RecurringList,
    RecurringOut,
    RecurringPatch,
)
from app.schemas.transactions import CategoryRef
from ml.recurring import (
    DetectedSeries,
    Occurrence,
    amount_change,
    detect,
    expected_dates,
    load_recurring_config,
    monthly_equivalent,
    series_status,
)

CENT = Decimal("0.01")
UPCOMING_DAYS = 7
CHANGE_HISTORY = 4  # the latest charge plus up to 3 before it (FR-08.03)


def money_str(value: Decimal) -> str:
    return f"{value.quantize(CENT, rounding=ROUND_HALF_UP):.2f}"


def interval_days(row: RecurringSeries) -> int:
    return int(Decimal(row.median_interval_days).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class RecurringService:
    def __init__(self, session: Session, user: User, now: dt.datetime | None = None) -> None:
        self.session = session
        self.user = user
        self.cfg = load_recurring_config()
        self.repo = RecurringSeriesRepository(session)
        self.tz = ZoneInfo(user.timezone)
        self.now = now or dt.datetime.now(dt.UTC)
        self.today = self.now.astimezone(self.tz).date()
        cats = CategoryRepository(session).list()
        self.by_id = {c.id: c for c in cats}

    # -- detection -----------------------------------------------------------------------------
    def detect(self, keys: Collection[str] | None = None) -> int:
        """Recompute series from the last 400 days (all merchants, or only ``keys``)."""
        since = dt.datetime.combine(
            self.today - dt.timedelta(days=self.cfg.lookback_days), dt.time.min, tzinfo=self.tz
        )
        rows = self.repo.occurrences(
            self.user.id, self.user.timezone, since, sorted(keys) if keys is not None else None
        )
        found = detect(
            (
                Occurrence(
                    transaction_id=str(tid),
                    merchant_key=key,
                    merchant_display=merchant or key.title(),
                    transaction_type=kind,
                    category_id=str(category_id),
                    day=day,
                    amount=amount,
                )
                for tid, key, merchant, kind, category_id, day, amount in rows
            ),
            self.today,
            self.cfg,
        )
        existing = {
            (s.merchant_key, s.transaction_type): s
            for s in self.repo.all(self.user.id)
            if keys is None or s.merchant_key in keys
        }
        links = self.repo.linked_ids(self.user.id, [s.id for s in existing.values()])
        seen: set[tuple[str, str]] = set()
        for series in found:
            slot = (series.merchant_key, series.transaction_type)
            seen.add(slot)
            row = existing.get(slot)
            if row is not None and row.status == "user_rejected":
                continue  # never suggested again (FR-08.05)
            if row is None:
                row = self._create(series)
                current: set[uuid.UUID] = set()
            else:
                self._update(row, series)
                current = links.get(row.id, set())
            target = {uuid.UUID(t) for t in series.transaction_ids}
            self.repo.unlink(self.user.id, row.id, current - target)
            self.repo.link(self.user.id, row.id, target - current)
        stale = [
            s.id
            for slot, s in existing.items()
            if slot not in seen and s.status not in ("user_confirmed", "user_rejected")
        ]
        self.repo.delete_many(self.user.id, stale)
        self.session.flush()
        return len(found)

    def refresh_for_transactions(self, transaction_ids: Collection[uuid.UUID]) -> None:
        """FR-08.06: a new or edited transaction of a known recurring merchant."""
        keys = self.repo.known_keys_of(self.user.id, transaction_ids)
        if keys:
            self.detect(keys)

    def _create(self, s: DetectedSeries) -> RecurringSeries:
        row = RecurringSeries(
            id=new_uuid7(),
            merchant_key=s.merchant_key,
            transaction_type=s.transaction_type,
            status=s.status,
        )
        self._fill(row, s)
        return self.repo.add(self.user.id, row)

    def _update(self, row: RecurringSeries, s: DetectedSeries) -> None:
        self._fill(row, s)
        if row.status != "user_confirmed":
            row.status = s.status  # a confirmation is the user's; the rules never undo it

    @staticmethod
    def _fill(row: RecurringSeries, s: DetectedSeries) -> None:
        row.merchant_display = s.merchant_display
        row.category_id = uuid.UUID(s.category_id)
        row.frequency = s.frequency
        row.median_interval_days = s.median_interval_days
        row.expected_amount = s.expected_amount
        row.amount_cv = s.amount_cv
        row.last_date = s.last_date
        row.next_expected_date = s.next_expected_date
        row.occurrences = s.occurrences
        row.confidence = s.confidence

    # -- status and amounts --------------------------------------------------------------------
    def live_status(self, row: RecurringSeries) -> str:
        """``active``/``paused``/``ended``; a confirmed series is judged by its dates too."""
        if row.status != "user_confirmed":
            return row.status
        return series_status(
            self.today,
            row.next_expected_date,
            float(row.median_interval_days),
            self.cfg.frequency(row.frequency),
            self.cfg,
        )

    @staticmethod
    def effective_amount(row: RecurringSeries) -> Decimal:
        return Decimal(row.user_expected_amount or row.expected_amount)

    def monthly_amount(self, row: RecurringSeries) -> Decimal:
        return monthly_equivalent(self.effective_amount(row), self.cfg.frequency(row.frequency))

    def _decomposes(self, row: RecurringSeries) -> bool:
        """7.7.1: confident (or confirmed) series split the forecast; the rest stay in the rate."""
        if row.status == "user_rejected":
            return False
        return row.status == "user_confirmed" or float(row.confidence) >= self.cfg.decomposition_min

    # -- API -----------------------------------------------------------------------------------
    def overview(self) -> RecurringList:
        self.detect()
        rows = [r for r in self.repo.all(self.user.id) if r.status != "user_rejected"]
        amounts = self.repo.recent_amounts(self.user.id, [r.id for r in rows], CHANGE_HISTORY)
        items = [self._out(r, amounts.get(r.id, [])) for r in rows]
        live = [(r, o) for r, o in zip(rows, items, strict=True) if self.live_status(r) == "active"]
        horizon = self.today + dt.timedelta(days=UPCOMING_DAYS)
        return RecurringList(
            items=items,
            monthly_expense_total=money_str(
                sum(
                    (self.monthly_amount(r) for r, _ in live if r.transaction_type == "expense"),
                    Decimal(0),
                )
            ),
            monthly_income_total=money_str(
                sum(
                    (self.monthly_amount(r) for r, _ in live if r.transaction_type == "income"),
                    Decimal(0),
                )
            ),
            upcoming=[o for r, o in live if max(r.next_expected_date, self.today) <= horizon],
            detection_version=self.cfg.version,
        )

    def patch(self, series_id: uuid.UUID, body: RecurringPatch) -> RecurringOut:
        row = self.repo.require(self.user.id, series_id)
        if "user_expected_amount" in body.model_fields_set:
            if body.user_expected_amount is not None and (
                body.user_expected_amount > get_settings().max_transaction_amount
            ):
                raise validation_problem(
                    "user_expected_amount", "AMOUNT_OUT_OF_RANGE", "Amount is above the maximum."
                )
            row.user_expected_amount = body.user_expected_amount
        if body.status is not None:
            row.status = body.status
        self.session.flush()
        amounts = self.repo.recent_amounts(self.user.id, [row.id], CHANGE_HISTORY)
        return self._out(row, amounts.get(row.id, []))

    def _out(self, row: RecurringSeries, recent: list[Decimal]) -> RecurringOut:
        category = self.by_id[row.category_id]
        change = amount_change(recent, self.cfg)
        return RecurringOut(
            id=row.id,
            merchant_key=row.merchant_key,
            merchant_display=row.merchant_display,
            transaction_type=row.transaction_type,  # type: ignore[arg-type]
            category=CategoryRef(id=category.id, slug=category.slug, name=category.name),
            frequency=row.frequency,  # type: ignore[arg-type]
            median_interval_days=float(row.median_interval_days),
            expected_amount=money_str(row.expected_amount),
            user_expected_amount=money_str(row.user_expected_amount)
            if row.user_expected_amount is not None
            else None,
            effective_amount=money_str(self.effective_amount(row)),
            monthly_equivalent=money_str(self.monthly_amount(row)),
            amount_cv=float(row.amount_cv),
            last_date=row.last_date,
            next_expected_date=row.next_expected_date,
            occurrences=row.occurrences,
            confidence=float(row.confidence),
            status=row.status,  # type: ignore[arg-type]
            amount_change=AmountChangeOut(
                previous_amount=money_str(change.previous_amount),
                latest_amount=money_str(change.latest_amount),
            )
            if change
            else None,
        )

    # -- forecast inputs (7.7.1, FR-07.04) -----------------------------------------------------
    def _remaining(
        self, kind: str, period_end: dt.date, category_id: uuid.UUID | None
    ) -> list[tuple[dt.date, Decimal]]:
        out: list[tuple[dt.date, Decimal]] = []
        for row in self.repo.all(self.user.id):
            if row.transaction_type != kind or not self._decomposes(row):
                continue
            if category_id is not None and row.category_id != category_id:
                continue
            for day in expected_dates(
                row.next_expected_date,
                interval_days(row),
                self.live_status(row),
                self.today,
                period_end,
            ):
                out.append((day, self.effective_amount(row)))
        return sorted(out)

    def expected_expenses(
        self, period_end: dt.date, category_id: uuid.UUID | None
    ) -> list[tuple[dt.date, Decimal]]:
        """Recurring expense charges still expected from today to ``period_end``."""
        return self._remaining("expense", period_end, category_id)

    def expected_income(self, period_end: dt.date) -> Decimal:
        """Recurring income still expected from today to ``period_end`` (FR-07.04)."""
        return sum((a for _, a in self._remaining("income", period_end, None)), Decimal(0))
