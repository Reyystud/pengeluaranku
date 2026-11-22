"""Shadow settings from ``config/shadow.yaml`` (versioned, PRD 0.3 rule 3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "shadow.yaml"


@dataclass(frozen=True)
class ShadowConfig:
    version: str
    min_days: float
    min_predictions: int
    lookback_days: int
    agreement_min: float
    corrected_accuracy_margin: float
    min_corrected_items: int
    require_corrections: bool
    p95_slo_ms: float
    psi_max: float
    psi_epsilon: float
    max_error_rate: float


def load_config(path: Path = CONFIG_PATH) -> ShadowConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ShadowConfig(
        version=str(raw["version"]),
        min_days=float(raw["min_days"]),
        min_predictions=int(raw["min_predictions"]),
        lookback_days=int(raw["lookback_days"]),
        agreement_min=float(raw["agreement_min"]),
        corrected_accuracy_margin=float(raw["corrected_accuracy_margin"]),
        min_corrected_items=int(raw["min_corrected_items"]),
        require_corrections=bool(raw["require_corrections"]),
        p95_slo_ms=float(raw["p95_slo_ms"]),
        psi_max=float(raw["psi_max"]),
        psi_epsilon=float(raw["psi_epsilon"]),
        max_error_rate=float(raw["max_error_rate"]),
    )
