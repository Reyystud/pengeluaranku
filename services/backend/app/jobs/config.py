"""Typed view of ``config/jobs.yaml`` (PRD 12.3, 15)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ml.config import _load_yaml


@dataclass(frozen=True)
class JobsConfig:
    version: str
    chunk_size: int
    active_days: int
    recurring_due_soon_days: int
    review_queue_min: int
    recategorize_batch: int
    retention_days: dict[str, int]


@lru_cache(maxsize=1)
def load_jobs_config() -> JobsConfig:
    raw = _load_yaml("jobs.yaml")
    return JobsConfig(
        version=str(raw["version"]),
        chunk_size=int(raw["chunk_size"]),
        active_days=int(raw["active_days"]),
        recurring_due_soon_days=int(raw["recurring_due_soon_days"]),
        review_queue_min=int(raw["review_queue_min"]),
        recategorize_batch=int(raw["recategorize_batch"]),
        retention_days={str(k): int(v) for k, v in raw["retention_days"].items()},
    )
