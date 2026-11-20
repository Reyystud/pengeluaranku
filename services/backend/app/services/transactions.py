"""Transaction create/read/update/delete, filters, pagination and duplicate flags (FR-02)."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.cursor import Cursor, decode_cursor, encode_cursor
from app.core.errors import ProblemError, not_found, validation_problem
from app.core.metrics import CATEGORIZE_PREVIEW
from app.core.text import clean_text, mask_long_numbers
from app.events.outbox import enqueue
from app.models import (
    Category,
    CategoryFeedback,
    CategoryPrediction,
    MerchantRule,
    Transaction,
    User,
)
from app.models.base import utcnow
from app.repositories import (
    CategoryFeedbackRepository,
    CategoryPredictionRepository,
    CategoryRepository,
    MerchantRuleRepository,
    TransactionFilters,
    TransactionRepository,
)
from app.repositories.categorization import MAX_RULES_PER_USER
from app.schemas.transactions import (
    Categorization,
    CategorizePreview,
    CategorizePreviewOut,
    CategoryRef,
    TransactionCreate,
    TransactionCreated,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TransactionUpdated,
    normalize_payment_method,
)
from app.services.budgets import BudgetService
from app.services.categorization import (
    CategorizationResult,
    CategorizeInput,
    Categorizer,
    FallbackCategorizer,
)
from ml.preprocessing import resolve_merchant
from ml.taxonomy import UNCATEGORIZED

MIN_DATE = dt.date(2000, 1, 1)
MAX_FUTURE = dt.timedelta(days=1)
DEFAULT_LIMIT, MAX_LIMIT = 50, 200
RE_SCORE_FIELDS = ("amount", "transaction_date", "transaction_type", "merchant")
MODEL_STATUSES = ("auto", "suggested", "needs_review", "rule")  # not chosen by the user


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
        self.predictions = CategoryPredictionRepository(session)
        self.feedback = CategoryFeedbackRepository(session)
        self.rules = MerchantRuleRepository(session)
        self.tz = ZoneInfo(user.timezone)
        cats = CategoryRepository(session).list()
        self.by_slug = {c.slug: c for c in cats}
        self.by_id = {c.id: c for c in cats}
        self.categorizer: Categorizer = categorizer or FallbackCategorizer(self.by_slug)

    def check_budgets(self) -> None:
        """Threshold notifications after any write that can change spending (FR-05.06)."""
        BudgetService(self.session, self.user).evaluate()

    # -- validation helpers -------------------------------------------------------------------
    def clean_field(
        self, name: str, value: str | None, *, maximum: int, required: bool
    ) -> str | None:
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

    def check_amount(self, amount: Decimal) -> None:
        if amount > self.settings.max_transaction_amount:
            raise validation_problem(
                "amount", "AMOUNT_OUT_OF_RANGE", "Amount is above the allowed maximum."
            )

    def resolve_when(self, value: dt.date | dt.datetime) -> tuple[dt.datetime, bool]:
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

    def find_duplicate_of(self, tx: Transaction) -> Transaction | None:
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

    def emit(self, event_type: str, tx: Transaction) -> None:
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
        self.check_amount(data.amount)
        description = self.clean_field("description", data.description, maximum=200, required=True)
        assert description is not None
        merchant_in = self.clean_field("merchant", data.merchant, maximum=100, required=False)
        notes = self.clean_field("notes", data.notes, maximum=500, required=False)
        occurred_at, has_time = self.resolve_when(data.transaction_date)
        merchant, merchant_key = resolve_merchant(merchant_in, description)

        if data.category:
            category = self.resolve_category(data.category, data.transaction_type)
            result = CategorizationResult(category, "user_set", "auto_apply", "user")
        else:
            result = self.categorizer.categorize(
                self.user,
                CategorizeInput(
                    transaction_type=data.transaction_type,
                    description=description,
                    merchant=merchant,
                    merchant_key=merchant_key,
                    amount=data.amount,
                    payment_method=data.payment_method,
                    occurred_at=occurred_at,
                    has_time=has_time,
                ),
                self.request_id,
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
        duplicate = self.find_duplicate_of(tx)
        if duplicate is not None:
            tx.possible_duplicate_of = duplicate.id
            warnings.append("POSSIBLE_DUPLICATE")
        self.session.flush()
        self.record_prediction(tx, result)
        self.emit("transaction.created", tx)
        self.check_budgets()
        base = self._out(tx)
        return TransactionCreated(
            **base.model_dump(), categorization=self.categorization_out(result), warnings=warnings
        )

    # -- categorization helpers ----------------------------------------------------------------
    def categorization_out(self, result: CategorizationResult) -> Categorization:
        return Categorization(
            decision=result.decision,
            source=result.source,
            confidence=result.confidence,
            alternatives=list(result.alternatives),
            model_version=result.model_version,
            predicted_category=result.predicted.slug if result.predicted else None,
            ml_error=result.ml_error,
        )

    def prediction_row(
        self, tx_id: uuid.UUID, result: CategorizationResult, request_id: str | None
    ) -> CategoryPrediction:
        predicted = result.predicted or result.category
        confidence = None if result.confidence is None else Decimal(f"{result.confidence:.4f}")
        return CategoryPrediction(
            transaction_id=tx_id,
            source={"rule": "user_rule", "model": "model"}.get(result.source, "fallback"),
            predicted_category_id=predicted.id,
            confidence=confidence,
            decision=result.decision,
            alternatives=list(result.alternatives),
            model_version=result.model_version,
            feature_version=result.feature_version,
            latency_ms=None if result.latency_ms is None else round(result.latency_ms),
            ml_error=result.ml_error,
            request_id=request_id or uuid.uuid4().hex,
        )

    def record_prediction(self, tx: Transaction, result: CategorizationResult) -> None:
        """FR-03.03: every rule/model/fallback decision is stored, even if the user overrides it."""
        if result.source == "user":
            return  # a category given by the user involves no prediction
        self.predictions.add(self.user.id, self.prediction_row(tx.id, result, self.request_id))
        if result.rule_id:
            self.rules.mark_applied(self.user.id, [result.rule_id])

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
    ) -> TransactionUpdated:
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
            self.check_amount(data.amount)
            tx.amount = data.amount
        if "description" in sent:
            desc = self.clean_field("description", data.description, maximum=200, required=True)
            assert desc is not None
            tx.description = desc
        if "notes" in sent:
            tx.notes = self.clean_field("notes", data.notes, maximum=500, required=False)
        if "payment_method" in sent and data.payment_method:
            tx.payment_method = data.payment_method
        if "transaction_date" in sent:
            if data.transaction_date is None:
                raise validation_problem("transaction_date", "INVALID_DATE", "Date is required.")
            tx.transaction_date, tx.has_time = self.resolve_when(data.transaction_date)
        if "merchant" in sent:
            merchant_in = self.clean_field("merchant", data.merchant, maximum=100, required=False)
            tx.merchant, tx.merchant_key = resolve_merchant(merchant_in, tx.description)
        tx.transaction_type = new_type

        current = self.by_id[tx.category_id]
        applied_to_past = 0
        if "category" in sent and data.category:
            category = self.resolve_category(data.category, new_type)
            applied_to_past = self.change_category(
                tx, category, apply_to_past=data.apply_to_past_merchant_transactions
            )
        elif data.apply_to_past_merchant_transactions:
            raise validation_problem(
                "apply_to_past_merchant_transactions",
                "INVALID_VALUE",
                "Only valid together with a category change.",
            )
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
            duplicate = self.find_duplicate_of(tx)
            tx.possible_duplicate_of = duplicate.id if duplicate else None
        tx.version += 1
        tx.updated_at = utcnow()
        self.session.flush()
        if changed:
            self.emit("transaction.updated", tx)
        self.check_budgets()
        return TransactionUpdated(**self._out(tx).model_dump(), applied_to_past=applied_to_past)

    # -- category changes: feedback, merchant memory (FR-03.04, FR-03.08, FR-10.01) ----------------
    def change_category(self, tx: Transaction, category: Category, *, apply_to_past: bool) -> int:
        """Apply a user's category choice. Returns how many past transactions it also changed."""
        previous_id, previous_status = tx.category_id, tx.category_status
        changed = category.id != previous_id
        confirmed = not changed and previous_status == "suggested"
        latest = self.predictions.latest_for(self.user.id, tx.id)
        tx.category_id = category.id
        tx.category_status = "user_confirmed" if confirmed else "user_set"

        if previous_status in MODEL_STATUSES and (changed or confirmed):
            picks = {self.by_id[latest.predicted_category_id].slug} if latest else set()
            if latest:
                picks |= {a["category"] for a in latest.alternatives}
            if confirmed:
                kind = "confirmation"
            elif previous_status == "needs_review" and category.slug in picks:
                kind = "quick_pick"
            else:
                kind = "correction"
            self.feedback.add(
                self.user.id,
                CategoryFeedback(
                    transaction_id=tx.id,
                    prediction_id=latest.id if latest else None,
                    previous_category_id=previous_id,
                    new_category_id=category.id,
                    previous_status=previous_status,
                    feedback_type=kind,
                    model_version=latest.model_version if latest else None,
                    merchant_key=tx.merchant_key,
                ),
            )

        past = 0
        if tx.merchant_key and category.slug != UNCATEGORIZED:
            if changed:
                self._remember_merchant(tx, category)
            if apply_to_past:
                types = (
                    ("income", "expense", "transfer")
                    if category.transaction_type == "any"
                    else (category.transaction_type,)
                )
                past = self.repo.apply_category_to_merchant(
                    self.user.id, tx.merchant_key, category.id, types, exclude_id=tx.id
                )
        return past

    def _remember_merchant(self, tx: Transaction, category: Category) -> None:
        """Upsert the merchant rule; at the 1,000-rule cap (FR-15.03) no new rule is added."""
        rule = self.rules.get_by_key(self.user.id, tx.merchant_key)
        if rule is not None:
            rule.category_id = category.id
            rule.updated_at = utcnow()
        elif self.rules.count(self.user.id) < MAX_RULES_PER_USER:
            now = utcnow()
            self.rules.add(
                self.user.id,
                MerchantRule(
                    merchant_key=tx.merchant_key,
                    merchant_display=(tx.merchant or tx.description)[:100],
                    category_id=category.id,
                    times_applied=0,
                    created_at=now,
                    updated_at=now,
                ),
            )

    def confirm_category(self, tx_id: uuid.UUID) -> TransactionOut:
        tx = self.repo.get_for_update(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        if tx.category_status != "suggested":
            raise ProblemError(
                409,
                "NOT_A_SUGGESTION",
                "Nothing to confirm",
                "Only a suggested category can be confirmed.",
            )
        self.change_category(tx, self.by_id[tx.category_id], apply_to_past=False)
        tx.version += 1
        tx.updated_at = utcnow()
        self.session.flush()
        return self._out(tx)

    def recategorize(self, tx_id: uuid.UUID, *, force: bool) -> TransactionCreated:
        """Re-run rule/model for one stored transaction (FR-03.09)."""
        tx = self.repo.get_for_update(self.user.id, tx_id)
        if tx is None:
            raise not_found()
        if tx.category_status in ("user_set", "user_confirmed") and not force:
            raise ProblemError(
                409,
                "CATEGORY_LOCKED",
                "Category is locked",
                "The category was chosen by the user; pass force=true to override it.",
            )
        result = self.categorizer.categorize(
            self.user,
            CategorizeInput(
                transaction_type=tx.transaction_type,
                description=tx.description,
                merchant=tx.merchant or "",
                merchant_key=tx.merchant_key,
                amount=tx.amount,
                payment_method=tx.payment_method,
                occurred_at=tx.transaction_date,
                has_time=tx.has_time,
            ),
            self.request_id,
        )
        tx.category_id = result.category.id
        tx.category_status = result.status
        tx.version += 1
        tx.updated_at = utcnow()
        self.session.flush()
        self.record_prediction(tx, result)
        self.check_budgets()
        return TransactionCreated(
            **self._out(tx).model_dump(),
            categorization=self.categorization_out(result),
            warnings=[],
        )

    def preview_category(self, data: CategorizePreview) -> CategorizePreviewOut:
        """FR-03.07: what would happen for a draft. Nothing is stored or counted."""
        description = self.clean_field("description", data.description, maximum=200, required=True)
        assert description is not None
        merchant_in = self.clean_field("merchant", data.merchant, maximum=100, required=False)
        amount = data.amount or Decimal(self.settings.preview_default_amount)
        self.check_amount(amount)
        when = data.transaction_date or dt.datetime.now(self.tz)
        occurred_at, has_time = self.resolve_when(when)
        merchant, merchant_key = resolve_merchant(merchant_in, description)
        result = self.categorizer.categorize(
            self.user,
            CategorizeInput(
                transaction_type=data.transaction_type,
                description=description,
                merchant=merchant,
                merchant_key=merchant_key,
                amount=amount,
                payment_method=data.payment_method,
                occurred_at=occurred_at,
                has_time=has_time,
            ),
            self.request_id,
        )
        CATEGORIZE_PREVIEW.labels(result.decision).inc()
        category = result.category
        return CategorizePreviewOut(
            category=CategoryRef(id=category.id, slug=category.slug, name=category.name),
            category_status=result.status,
            categorization=self.categorization_out(result),
        )

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
        self.emit("transaction.deleted", tx)
        self.session.delete(tx)
        self.session.flush()
        self.check_budgets()

    def _bulk_rows(self, ids: list[uuid.UUID]) -> list[Transaction]:
        unique = list(dict.fromkeys(ids))
        rows = self.repo.get_many(self.user.id, unique)
        if len(rows) != len(unique):
            raise not_found()  # atomic: one unknown (or foreign) id fails the whole request
        return rows

    def bulk_delete(self, ids: list[uuid.UUID]) -> int:
        rows = self._bulk_rows(ids)
        for tx in rows:
            self.emit("transaction.deleted", tx)
            self.session.delete(tx)
        self.session.flush()
        self.check_budgets()
        return len(rows)

    def bulk_categorize(self, ids: list[uuid.UUID], category_ref: str) -> int:
        rows = self._bulk_rows(ids)
        category = None
        for tx in rows:
            category = self.resolve_category(category_ref, tx.transaction_type)
        assert category is not None
        updated = self.repo.set_category_many(
            self.user.id, [t.id for t in rows], category.id, "user_set"
        )
        self.check_budgets()
        return updated


def normalize_payment_method_or_422(value: str) -> str:
    try:
        return normalize_payment_method(value)
    except ValueError as exc:
        raise validation_problem(
            "payment_method", "INVALID_PAYMENT_METHOD", "Unknown payment method."
        ) from exc
