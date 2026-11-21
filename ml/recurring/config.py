"""Typed view of ``config/recurring.yaml`` (PRD 7.8, 0.3 rule 3)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache

from ml.config import _load_yaml


@dataclass(frozen=True)
class Frequency:
    name: str
    nominal_days: int
    min_days: int
    max_days: int
    tolerance_days: int
    per_year: int


@dataclass(frozen=True)
class RecurringConfig:
    version: str
    lookback_days: int
    min_occurrences: int
    min_regularity: float
    max_cv: float
    cv_penalty: float
    change_pct: Decimal
    change_min_amount: Decimal
    cluster_tolerance: Decimal
    cluster_candidates: int
    cluster_min_share: Decimal
    occurrences_saturate: int
    show_min: float
    decomposition_min: float
    ended_after_intervals: int
    frequencies: tuple[Frequency, ...]

    def frequency(self, name: str) -> Frequency:
        for f in self.frequencies:
            if f.name == name:
                return f
        raise KeyError(name)


@lru_cache(maxsize=1)
def load_recurring_config() -> RecurringConfig:
    d = _load_yaml("recurring.yaml")
    return RecurringConfig(
        version=str(d["version"]),
        lookback_days=int(d["lookback_days"]),
        min_occurrences=int(d["min_occurrences"]),
        min_regularity=float(d["min_regularity"]),
        max_cv=float(d["amount"]["max_cv"]),
        cv_penalty=float(d["amount"]["cv_penalty"]),
        change_pct=Decimal(str(d["amount"]["change_pct"])),
        change_min_amount=Decimal(str(d["amount"]["change_min_amount"])),
        cluster_tolerance=Decimal(str(d["amount"]["cluster_tolerance"])),
        cluster_candidates=int(d["amount"]["cluster_candidates"]),
        cluster_min_share=Decimal(str(d["amount"]["cluster_min_share"])),
        occurrences_saturate=int(d["confidence"]["occurrences_saturate"]),
        show_min=float(d["confidence"]["show_min"]),
        decomposition_min=float(d["confidence"]["decomposition_min"]),
        ended_after_intervals=int(d["status"]["ended_after_intervals"]),
        frequencies=tuple(
            Frequency(
                name=str(name),
                nominal_days=int(f["nominal_days"]),
                min_days=int(f["min_days"]),
                max_days=int(f["max_days"]),
                tolerance_days=int(f["tolerance_days"]),
                per_year=int(f["per_year"]),
            )
            for name, f in d["frequencies"].items()
        ),
    )
