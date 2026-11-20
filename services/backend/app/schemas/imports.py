"""CSV import request/response models (PRD 7.2.3, 13.2). Also the shape of ``staged_rows``."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.auth import StrictModel

RowStatus = Literal["valid", "invalid", "duplicate"]


class RowError(BaseModel):
    row_number: int
    column: str
    code: str
    message: str
    value: str | None = None  # the offending cell, truncated to 50 chars


class RowValues(BaseModel):
    transaction_type: str
    amount: str
    description: str
    merchant: str
    merchant_key: str
    transaction_date: str  # ISO 8601 with the user's UTC offset
    has_time: bool
    payment_method: str
    category: str  # slug
    category_status: str
    notes: str | None


class RowPrediction(BaseModel):
    category: str  # what is stored (uncategorized when the row needs review)
    predicted_category: str | None = None  # the top pick, for quick picks
    decision: str
    source: str  # rule | model | fallback
    confidence: float | None = None
    alternatives: list[dict[str, Any]] = []
    model_version: str | None = None
    feature_version: str | None = None
    latency_ms: float | None = None
    ml_error: str | None = None
    rule_id: uuid.UUID | None = None


class StagedRow(BaseModel):
    row_number: int
    status: RowStatus
    values: RowValues | None = None
    prediction: RowPrediction | None = None
    errors: list[RowError] = []
    duplicate_of: uuid.UUID | None = None  # an existing transaction
    duplicate_of_row: int | None = None  # an earlier row of the same file


class ImportWarning(BaseModel):
    code: str
    message: str
    columns: list[str] | None = None


class ImportSummary(BaseModel):
    row_count: int
    valid: int
    invalid: int
    duplicate: int


class ImportPreview(BaseModel):
    import_id: uuid.UUID
    status: str
    filename: str
    summary: ImportSummary
    rows: list[StagedRow]
    next_cursor: str | None
    warnings: list[ImportWarning]
    expires_at: dt.datetime


class CommitRequest(StrictModel):
    mode: Literal["strict", "skip_invalid"] = "strict"
    skip_duplicates: bool = True
    category_overrides: Annotated[dict[str, str], Field(max_length=5000)] = {}


class CommitResult(BaseModel):
    committed_count: int
    skipped_invalid: int
    skipped_duplicates: int
