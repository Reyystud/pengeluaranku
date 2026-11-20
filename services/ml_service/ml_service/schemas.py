"""Request/response models for the classifier endpoints (PRD 14.2). Unknown fields are rejected."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

PaymentMethod = Literal[
    "cash", "bank_transfer", "debit_card", "credit_card", "e_wallet", "qris", "other"
]
TransactionType = Literal["income", "expense", "transfer"]
MAX_AMOUNT = Decimal("1000000000000")


def _amount(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | Decimal):
        raise ValueError("amount must be a decimal string")
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise ValueError("amount must be a decimal string") from exc
    if not amount.is_finite() or amount <= 0 or amount > MAX_AMOUNT:
        raise ValueError("amount must be greater than 0 and within range")
    return amount


Amount = Annotated[Decimal, BeforeValidator(_amount)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassifyRequest(Strict):
    request_id: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    merchant_key: Annotated[str, Field(max_length=100)]
    amount: Amount
    payment_method: PaymentMethod
    transaction_type: TransactionType
    local_hour: Annotated[int, Field(ge=0, le=23)] | None  # null when the time is unknown
    weekday: Annotated[int, Field(ge=0, le=6)]  # Monday = 0, in the user's timezone
    feature_version: Annotated[str, Field(min_length=1, max_length=32)]


class Alternative(BaseModel):
    category: str
    confidence: float


class Thresholds(BaseModel):
    t_high: float
    t_low: float


class ClassifyResponse(BaseModel):
    predicted_category: str
    confidence: float
    decision: Literal["auto_apply", "suggest", "needs_review"]
    alternatives: list[Alternative]
    model_version: str
    feature_version: str
    thresholds: Thresholds
    latency_ms: float
    shadow: None = None  # filled by the shadow-mode task


class BatchRequest(Strict):
    request_id: Annotated[str, Field(min_length=1, max_length=64)]
    items: Annotated[list[ClassifyRequest], Field(min_length=1, max_length=500)]


class BatchResponse(BaseModel):
    items: list[ClassifyResponse]
