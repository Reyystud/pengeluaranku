"""Behavior segment response (PRD 7.13, FR-13.04)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel


class TraitOut(BaseModel):
    feature: str
    direction: Literal["higher", "lower"]
    percent: int
    value: float
    message: str


class SegmentInfo(BaseModel):
    id: str
    name: str
    description: str
    traits: list[TraitOut]
    model_version: str
    computed_at: dt.datetime


class SegmentOut(BaseModel):
    segment: SegmentInfo | None
    reason: Literal["NOT_COMPUTED", "INSUFFICIENT_HISTORY", "MODEL_NOT_AVAILABLE"] | None = None
    complete_periods: int
    required_periods: int
