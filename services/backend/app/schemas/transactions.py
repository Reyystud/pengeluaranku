"""Transaction request/response models (PRD 7.2.1, 13.2). Money is a string in JSON."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.models import Category, Transaction
from app.schemas.auth import StrictModel

TransactionType = Literal["income", "expense", "transfer"]
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PAYMENT_METHODS = (
    "cash",
    "bank_transfer",
    "debit_card",
    "credit_card",
    "e_wallet",
    "qris",
    "other",
)
_PAYMENT_ALIASES = {
    "bank": "bank_transfer",
    "card": "debit_card",
    "ewallet": "e_wallet",
    "qr": "qris",
}


def parse_amount(value: object) -> Decimal:
    """JSON number or string to ``Decimal(str(x))``; > 0 and at most 2 decimal places."""
    if isinstance(value, bool) or not isinstance(value, str | int | float | Decimal):
        raise ValueError("INVALID_AMOUNT: Amount must be a number.")
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount <= 0:
            raise ValueError("INVALID_AMOUNT: Amount must be greater than 0.")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("INVALID_AMOUNT: Amount can have at most 2 decimal places.")
    except InvalidOperation as exc:
        raise ValueError("INVALID_AMOUNT: Amount must be a number.") from exc
    return amount


def parse_when(value: object) -> dt.date | dt.datetime:
    """``YYYY-MM-DD`` is a date (no time); anything else must be an ISO 8601 datetime."""
    if isinstance(value, dt.datetime | dt.date):
        return value
    if not isinstance(value, str):
        raise ValueError("INVALID_DATE: Use YYYY-MM-DD or an ISO 8601 datetime.")
    text = value.strip()
    try:
        if _DATE_ONLY.match(text):
            return dt.date.fromisoformat(text)
        return dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("INVALID_DATE: Use YYYY-MM-DD or an ISO 8601 datetime.") from exc


def normalize_payment_method(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("INVALID_PAYMENT_METHOD: Unknown payment method.")
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    key = _PAYMENT_ALIASES.get(key, key)
    if key not in PAYMENT_METHODS:
        raise ValueError("INVALID_PAYMENT_METHOD: Unknown payment method.")
    return key


Amount = Annotated[Decimal, BeforeValidator(parse_amount)]
When = Annotated[dt.date | dt.datetime, BeforeValidator(parse_when)]
PaymentMethod = Annotated[str, BeforeValidator(normalize_payment_method)]
# Length limits are enforced after cleaning, in the service, so the codes match PRD 7.2.3.
Text = Annotated[str, Field(max_length=2000)]


class TransactionCreate(StrictModel):
    transaction_type: TransactionType
    amount: Amount
    description: Text
    merchant: Text | None = None
    transaction_date: When
    payment_method: PaymentMethod = "other"
    category: str | None = None  # slug or UUID; if given, status is user_set and no ML call
    notes: Text | None = None


class TransactionUpdate(StrictModel):
    apply_to_past_merchant_transactions: bool = False  # only with a category change (FR-03.08)
    transaction_type: TransactionType | None = None
    amount: Amount | None = None
    description: Text | None = None
    merchant: Text | None = None
    transaction_date: When | None = None
    payment_method: PaymentMethod | None = None
    category: str | None = None
    notes: Text | None = None


class BulkDelete(StrictModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]


class BulkCategorize(StrictModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=200)]
    category: str


class CategoryRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class CategoryOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    transaction_type: str


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)

    id: uuid.UUID
    transaction_type: str
    amount: str
    description: str
    merchant: str | None
    merchant_key: str
    transaction_date: str
    has_time: bool
    payment_method: str
    category: CategoryRef
    category_status: str
    notes: str | None
    source: str
    import_id: uuid.UUID | None
    possible_duplicate_of: uuid.UUID | None
    duplicate_dismissed: bool
    version: int
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def build(cls, tx: Transaction, category: Category, timezone: str) -> TransactionOut:
        from zoneinfo import ZoneInfo

        return cls(
            id=tx.id,
            transaction_type=tx.transaction_type,
            amount=f"{tx.amount:.2f}",
            description=tx.description,
            merchant=tx.merchant,
            merchant_key=tx.merchant_key,
            transaction_date=tx.transaction_date.astimezone(ZoneInfo(timezone)).isoformat(),
            has_time=tx.has_time,
            payment_method=tx.payment_method,
            category=CategoryRef(id=category.id, slug=category.slug, name=category.name),
            category_status=tx.category_status,
            notes=tx.notes,
            source=tx.source,
            import_id=tx.import_id,
            possible_duplicate_of=tx.possible_duplicate_of,
            duplicate_dismissed=tx.duplicate_dismissed,
            version=tx.version,
            created_at=tx.created_at,
            updated_at=tx.updated_at,
        )


class Categorization(BaseModel):
    decision: str
    source: str  # user | rule | model | fallback
    confidence: float | None
    alternatives: list[dict[str, Any]]  # [{category: slug, confidence}], quick picks for review
    model_version: str | None
    predicted_category: str | None = None  # the top pick, even when the row stays uncategorized
    ml_error: str | None = None  # timeout | unavailable | circuit_open | bad_response | ...


class TransactionCreated(TransactionOut):
    categorization: Categorization
    warnings: list[str]


class TransactionUpdated(TransactionOut):
    applied_to_past: int = 0  # past transactions of the merchant changed by the checkbox


class CategorizePreview(StrictModel):
    description: Text
    merchant: Text | None = None
    amount: Amount | None = None
    payment_method: PaymentMethod = "other"
    transaction_type: TransactionType
    transaction_date: When | None = None


class CategorizePreviewOut(BaseModel):
    category: CategoryRef
    category_status: str
    categorization: Categorization


class RecategorizeRequest(StrictModel):
    force: bool = False


class MerchantRuleOut(BaseModel):
    id: uuid.UUID
    merchant_key: str
    merchant_display: str
    category: CategoryRef
    times_applied: int
    last_applied_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class MerchantRuleUpdate(StrictModel):
    category: str


class MerchantRuleList(BaseModel):
    items: list[MerchantRuleOut]


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    next_cursor: str | None


class CountOut(BaseModel):
    count: int
