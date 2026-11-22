"""Drift settings from ``config/drift.yaml`` (versioned, PRD 0.3 rule 3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "drift.yaml"


@dataclass(frozen=True)
class DriftConfig:
    version: str
    window_days: int
    min_rows: int
    psi_threshold: float
    key_features: tuple[str, ...]
    numeric_features: tuple[str, ...]
    categorical_features: tuple[str, ...]
    unseen_ratio_threshold: float
    unseen_history_days: int
    unseen_min_history: int


def load_config(path: Path = CONFIG_PATH) -> DriftConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = DriftConfig(
        version=str(raw["version"]),
        window_days=int(raw["window_days"]),
        min_rows=int(raw["min_rows"]),
        psi_threshold=float(raw["psi_threshold"]),
        key_features=tuple(raw["key_features"]),
        numeric_features=tuple(raw["numeric_features"]),
        categorical_features=tuple(raw["categorical_features"]),
        unseen_ratio_threshold=float(raw["unseen_ratio_threshold"]),
        unseen_history_days=int(raw["unseen_history_days"]),
        unseen_min_history=int(raw["unseen_min_history"]),
    )
    columns = set(cfg.numeric_features) | set(cfg.categorical_features)
    if not set(cfg.key_features) <= columns:
        raise ValueError("key_features must be monitored columns")
    return cfg
