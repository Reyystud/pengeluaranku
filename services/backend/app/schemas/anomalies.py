"""Anomaly models (PRD 7.6, 13.2). Amounts are strings; scores are plain numbers in 0..1."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel

from app.schemas.transactions import CategoryRef

AnomalyType = Literal[
    "amount_spike", "frequency_burst", "new_merchant_high_value", "category_surge", "amount_low"
]
Severity = Literal["low", "medium", "high"]
AnomalyStatus = Literal["open", "confirmed", "dismissed", "historical", "superseded"]
FeedbackAction = Literal["confirm", "dismiss"]
DismissReason = Literal["expected_purchase", "wrong_amount", "not_mine", "other"]


class ReasonOut(BaseModel):
    code: str
    message: str
    feature: str
    value: float
    reference: float


class AnomalyTransaction(BaseModel):
    id: uuid.UUID
    transaction_date: dt.datetime
    amount: str
    merchant: str | None
    description: str


class AnomalyOut(BaseModel):
    id: uuid.UUID
    anomaly_type: AnomalyType
    severity: Severity
    status: AnomalyStatus
    is_alert: bool
    score: float
    history_level: Literal["personal", "limited"]
    category: CategoryRef | None
    period_id: dt.date
    reasons: list[ReasonOut]
    transaction: AnomalyTransaction | None
    model_version: str
    feedback_reason: DismissReason | None
    feedback_at: dt.datetime | None
    created_at: dt.datetime


class AnomalyPage(BaseModel):
    items: list[AnomalyOut]
    next_cursor: str | None


class AnomalyFeedback(BaseModel):
    action: FeedbackAction
    reason: DismissReason | None = None
