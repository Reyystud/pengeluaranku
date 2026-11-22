"""Insights API shapes (PRD 7.9, 13.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["info", "positive", "warning"]


class InsightOut(BaseModel):
    id: uuid.UUID
    rule_id: str
    rule_version: str
    period_id: dt.date
    subject_key: str
    severity: Severity
    priority: str
    title: str
    message: str
    message_key: str
    message_params: dict[str, str]
    evidence: dict[str, Any]
    dismissed_at: dt.datetime | None
    created_at: dt.datetime


class InsightList(BaseModel):
    period_id: dt.date
    items: list[InsightOut]


class RefreshOut(BaseModel):
    period_id: dt.date
    created: int
    removed: int
    total: int
