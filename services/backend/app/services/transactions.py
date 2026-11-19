"""Transaction create/read/update/delete, filters, pagination and duplicate flags (FR-02)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import ProblemError, not_found, validation_problem
from app.core.text import clean_text, mask_long_numbers
from app.events.outbox import enqueue
from app.models import Category, Transaction, User
from app.models.base import utcnow
from app.repositories import CategoryRepository, TransactionFilters, TransactionRepository
from app.schemas.transactions import (
    Categorization,
    TransactionCreate,
    TransactionCreated,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    normalize_payment_method,
)
from ml.preprocessing import resolve_merchant
from ml.taxonomy import UNCATEGORIZED

MIN_DATE = dt.date(2000, 1, 1)
MAX_FUTURE = dt.timedelta(days=1)
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
RE_SCORE_FIELDS = ("amount", "transaction_date", "transaction_type", "merchant")


@dataclass(frozen=True)
class CategorizationResult:
    category: Category
    status: str
    decision: str
    source: str
    confidence: float | None = None
    alternatives: list[dict[str, object]] = field(default_factory=list)
    model_version: str | None = None


class Categorizer(Protocol):
    """Seam for T-18 (merchant rules, ML client, circuit breaker). Must never raise."""

    def categorize(
        self,
        user: User,
        *,
        transaction_type: str,
        description: str,
        merchant: str,
        merchant_key: str,
        amount: Decimal,
        occurred_at: dt.datetime,
    ) -> CategorizationResult: ...


class FallbackCategorizer:
    """Until T-18: no rule, no model. Saving still succeeds (PRD 6.3) and the row needs review."""

    def __init__(self, categories: dict[str, Category]) -> None:
        self._uncategorized = categories[UNCATEGORIZED]

    def categorize(self, user: User, **_: object) -> CategorizationResult:
        return CategorizationResult(self._uncategorized, "needs_review", "needs_review", "fallback")


@dataclass
class ListQuery:
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    transaction_type: str | None = None
    category: list[str] = field(default_factory=list)
    payment_method: list[str] = field(default_factory=list)
    q: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    category_status: str | None = None
    possible_duplicate: bool | None = None
    sort: str = "date"
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None


class TransactionService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        user: User,
        request_id: str | None = None,
        categorizer: Categorizer | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.user = user
        self.request_id = request_id
        self.repo = TransactionRepository(session)
        self.tz = ZoneInfo(user.timezone)
        cats = CategoryRepository(session).list()
        self.by_slug = {c.slug: c for c in cats}
        self.by_id = {c.id: c for c in cats}
        self.categorizer: Categorizer = categorizer or FallbackCategorizer(self.by_slug)

    # -- validation helpers -------------------------------------------------------------------
    def _text(self, name: str, value: str | None, *, maximum: int, required: bool) -> str | None:
        if value is None:
            if required:
                raise validation_problem(name, "MISSING_FIELD", f"{name} is required.")
            return None
        cleaned = mask_long_numbers(clean_text(value, keep_newlines=name == "notes"))
        if not cleaned:
            if required:
                raise validation_problem(name, "MISSING_FIELD", f"{name} is required.")
            return None
        if len(cleaned) > maximum:
            raise validation_problem(
                name, "FIELD_TOO_LONG", f"{name} must be at most {maximum} characters."
            )
        return cleaned

    def _check_amount(self, amount: Decimal) -> None:
        if amount > self.settings.max_transaction_amount:
            raise validation_problem(
                "amount", "AMOUNT_OUT_OF_RANGE", "Amount is above the allowed maximum."
            )

    def _when(self, value: dt.date | dt.datetime) -> tuple[dt.datetime, bool]:
        """Return ``(UTC instant, has_time)``; naive values are in the user's timezone."""
        if isinstance(value, dt.datetime):
            local = value if value.tzinfo else value.replace(tzinfo=self.tz)
            has_time = True
        else:
            local = dt.datetime.combine(value, dt.time.min, tzinfo=self.tz)
            has_time = False
        local_date = local.astimezone(self.tz).date()
        today = dt.datetime.now(self.tz).date()
        if local_date < MIN_DATE:
            raise validation_problem(
                "transaction_date", "INVALID_DATE", "Date must be on or after 2000-01-01."
            )
        if local_date > today + MAX_FUTURE:
            raise validation_problem(
                "transaction_date", "FUTURE_DATE", "Date is too far in the future."
            )
        return local.astimezone(dt.UTC), has_time

    def resolve_category(self, ref: str, transaction_type: str) -> Category:
        category: Category | None = None
        try:
            category = self.by_id.get(uuid.UUID(ref))
        except ValueError:
            category = self.by_slug.get(ref.strip().lower())
        if category is None:
            raise validation_problem("category", "UNKNOWN_CATEGORY", "Unknown category.")
        if category.transaction_type not in ("any", transaction_type):
            raise validation_problem(
                "category",
                "CATEGORY_TYPE_MISMATCH",
                "This category cannot be used with this transaction type.",
            )
        return category

    def _out(self, tx: Transaction) -> TransactionOut:
        return TransactionOut.build(tx, self.by_id[tx.category_id], self.user.timezone)

    def _find_duplicate(self, tx: Transaction) -> Transaction | None:
        return self.repo.find_duplicate(
            self.user.id,
            transaction_type=tx.transaction_type,
            amount=tx.amount,
            merchant_key=tx.merchant_key,
            occurred_at=tx.transaction_date,
            has_time=tx.has_time,
            timezone=self.user.timezone,
            exclude_id=tx.id,
        )

    def _emit(self, event_type: str, tx: Transaction) -> None:
        enqueue(
            self.session,
            event_type,
            user_id=self.user.id,
            aggregate_id=tx.id,
            request_id=self.request_id,
            data={
                "transaction_id": str(tx.id),
                "transaction_version": tx.version,
                "transaction_type": tx.transaction_type,
                "source": tx.source,
                "import_id": str(tx.import_id) if tx.import_id else None,
            },
        )

    # -- create -------------------------------------------------------------------------------
    def create(self, data: TransactionCreate) -> TransactionCreated:
        self._check_amount(data.amount)
        description = self._text("description", data.description, maximum=200, required=True)
        assert description is not None
        merchant_in = self._text("merchant", data.merchant, maximum=100, required=False)
        notes = self._text("notes", data.notes, maximum=500, required=False)
        occurred_at, has_time = self._when(data.transaction_date)
        merchant, merchant_key = resolve_merchant(merchant_in, description)

        if data.category:
            category = self.resolve_category(data.category, data.transaction_type)
            result = CategorizationResult(category, "user_set", "auto_apply", "user")
        else:
            result = self.categorizer.categorize(
                self.user,
                transaction_type=data.transaction_type,
                description=description,
                merchant=merchant,
                merchant_key=merchant_key,
                amount=data.amount,
                occurred_at=occurred_at,
            )

        tx = Transaction(
            transaction_type=data.transaction_type,
            amount=data.amount,
            description=description,
            merchant=merchant,
            merchant_key=merchant_key,
            transaction_date=occurred_at,
            has_time=has_time,
            payment_method=data.payment_method,
            category_id=result.category.id,
            category_status=result.status,
            notes=notes,
            source="manual",
        )
        warnings: list[str] = []
        self.repo.add(self.user.id, tx)
        duplicate = self._find_duplicate(tx)
        if duplicate is not None:
            tx.possible_duplicate_of = duplicate.id
            warnings.append("POSSIBLE_DUPLICATE")
        self.session.flush()
        self._emit("transaction.created", tx)
        base = self._out(tx)
        return TransactionCreated(
            **base.model_dump(),
            categorization=Categorization(
                decision=result.decision,
                source=result.source,
                confidence=result.confidence,
                alternatives=list(result.alternatives),
                model_version=result.model_version,
            ),
            warnings=warnings,
        )

    # -- read ---------------------------------------------------------------------------------
    def get(self, tx_id: uuid.UUID) -> TransactionOut:
        tx = self.repo.get(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        return self._out(tx)

    def _filters(self, q: ListQuery) -> TransactionFilters:
        start = end = None
        if q.date_from is not None:
            start = dt.datetime.combine(q.date_from, dt.time.min, tzinfo=self.tz)
        if q.date_to is not None:
            end = dt.datetime.combine(q.date_to + dt.timedelta(days=1), dt.time.min, tzinfo=self.tz)
        category_ids = [self.resolve_filter_category(ref).id for ref in q.category]
        methods = [normalize_payment_method_or_422(m) for m in q.payment_method]
        return TransactionFilters(
            start=start,
            end=end,
            transaction_type=q.transaction_type,
            category_ids=category_ids,
            payment_methods=methods,
            q=(q.q or "").strip() or None,
            min_amount=q.min_amount,
            max_amount=q.max_amount,
            category_status=q.category_status,
            possible_duplicate=q.possible_duplicate,
        )

    def resolve_filter_category(self, ref: str) -> Category:
        try:
            found = self.by_id.get(uuid.UUID(ref))
        except ValueError:
            found = self.by_slug.get(ref.strip().lower())
        if found is None:
            raise validation_problem("category", "UNKNOWN_CATEGORY", "Unknown category.")
        return found

    def search(self, q: ListQuery) -> TransactionPage:
        secret = self.settings.cursor_signing_key.get_secret_value()
        after = decode_cursor(q.cursor, self.user.id, secret, q.sort) if q.cursor else None
        rows = self.repo.search(
            self.user.id, self._filters(q), sort=q.sort, limit=q.limit + 1, after=after
        )
        page, more = rows[: q.limit], len(rows) > q.limit
        next_cursor = None
        if more and page:
            last = page[-1]
            key = (
                f"{last.amount:.2f}"
                if q.sort == "amount"
                else last.transaction_date.astimezone(dt.UTC).isoformat()
            )
            next_cursor = encode_cursor(Cursor(q.sort, key, last.id), self.user.id, secret)
        return TransactionPage(items=[self._out(t) for t in page], next_cursor=next_cursor)

    def count(self, q: ListQuery) -> int:
        return self.repo.count_matching(self.user.id, self._filters(q))

    # -- update -------------------------------------------------------------------------------
    def update(
        self, tx_id: uuid.UUID, data: TransactionUpdate, if_match: str | None = None
    ) -> TransactionOut:
        tx = self.repo.get_for_update(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        if if_match is not None:
            self._check_version(tx, if_match)
        sent = data.model_fields_set
        before = {
            "amount": tx.amount,
            "transaction_date": tx.transaction_date,
            "transaction_type": tx.transaction_type,
            "merchant": tx.merchant_key,
        }

        new_type = (
            data.transaction_type
            if "transaction_type" in sent and data.transaction_type
            else tx.transaction_type
        )
        if "amount" in sent:
            if data.amount is None:
                raise validation_problem("amount", "INVALID_AMOUNT", "Amount must be a number.")
            self._check_amount(data.amount)
            tx.amount = data.amount
        if "description" in sent:
            desc = self._text("description", data.description, maximum=200, required=True)
            assert desc is not None
            tx.description = desc
        if "notes" in sent:
            tx.notes = self._text("notes", data.notes, maximum=500, required=False)
        if "payment_method" in sent and data.payment_method:
            tx.payment_method = data.payment_method
        if "transaction_date" in sent:
            if data.transaction_date is None:
                raise validation_problem("transaction_date", "INVALID_DATE", "Date is required.")
            tx.transaction_date, tx.has_time = self._when(data.transaction_date)
        if "merchant" in sent:
            merchant_in = self._text("merchant", data.merchant, maximum=100, required=False)
            tx.merchant, tx.merchant_key = resolve_merchant(merchant_in, tx.description)
        tx.transaction_type = new_type

        current = self.by_id[tx.category_id]
        if "category" in sent and data.category:
            category = self.resolve_category(data.category, new_type)
            same_suggestion = category.id == tx.category_id and tx.category_status == "suggested"
            tx.category_id = category.id
            tx.category_status = "user_confirmed" if same_suggestion else "user_set"
        elif current.transaction_type not in ("any", new_type):
            # The type changed under an existing category: fall back and flag for review.
            tx.category_id = self.by_slug[UNCATEGORIZED].id
            tx.category_status = "needs_review"

        after = {
            "amount": tx.amount,
            "transaction_date": tx.transaction_date,
            "transaction_type": tx.transaction_type,
            "merchant": tx.merchant_key,
        }
        changed = [k for k in RE_SCORE_FIELDS if before[k] != after[k]]
        if changed and not tx.duplicate_dismissed:
            duplicate = self._find_duplicate(tx)
            tx.possible_duplicate_of = duplicate.id if duplicate else None
        tx.version += 1
        tx.updated_at = utcnow()
        self.session.flush()
        if changed:
            self._emit("transaction.updated", tx)
        return self._out(tx)

    @staticmethod
    def _check_version(tx: Transaction, if_match: str) -> None:
        raw = if_match.strip()
        if raw.startswith("W/"):
            raw = raw[2:]
        try:
            expected = int(raw.strip('"'))
        except ValueError as exc:
            raise ProblemError(
                400, "BAD_REQUEST", "Bad request", 'If-Match must be the version, e.g. "3".'
            ) from exc
        if expected != tx.version:
            raise ProblemError(
                409,
                "VERSION_CONFLICT",
                "Version conflict",
                "The transaction was changed by another request. Reload and try again.",
            )

    def dismiss_duplicate(self, tx_id: uuid.UUID) -> TransactionOut:
        tx = self.repo.get_for_update(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        tx.possible_duplicate_of = None
        tx.duplicate_dismissed = True
        tx.version += 1
        self.session.flush()
        return self._out(tx)

    # -- delete / bulk ------------------------------------------------------------------------
    def delete(self, tx_id: uuid.UUID) -> None:
        tx = self.repo.get_for_update(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        self._emit("transaction.deleted", tx)
        self.session.delete(tx)
        self.session.flush()

    def _bulk_rows(self, ids: list[uuid.UUID]) -> list[Transaction]:
        unique = list(dict.fromkeys(ids))
        rows = self.repo.get_many(self.user.id, unique)
        if len(rows) != len(unique):
            raise not_found()  # atomic: one unknown (or foreign) id fails the whole request
        return rows

    def bulk_delete(self, ids: list[uuid.UUID]) -> int:
        rows = self._bulk_rows(ids)
        for tx in rows:
            self._emit("transaction.deleted", tx)
            self.session.delete(tx)
        self.session.flush()
        return len(rows)

    def bulk_categorize(self, ids: list[uuid.UUID], category_ref: str) -> int:
        rows = self._bulk_rows(ids)
        category = None
        for tx in rows:
            category = self.resolve_category(category_ref, tx.transaction_type)
        assert category is not None
        return self.repo.set_category_many(
            self.user.id, [t.id for t in rows], category.id, "user_set"
        )


def normalize_payment_method_or_422(value: str) -> str:
    try:
        return normalize_payment_method(value)
    except ValueError as exc:
        raise validation_problem(
            "payment_method", "INVALID_PAYMENT_METHOD", "Unknown payment method."
        ) from exc
