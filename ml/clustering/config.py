"""Typed view of ``config/clustering.yaml``."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ml.config import _load_yaml


@dataclass(frozen=True)
class ClusteringConfig:
    version: str
    seed: int
    periods: int
    min_periods: int
    small_tx_amount: float
    clr_epsilon: float
    trait_count: int
    trait_min_deviation: float


@lru_cache(maxsize=1)
def load_clustering_config() -> ClusteringConfig:
    d = _load_yaml("clustering.yaml")
    return ClusteringConfig(
        version=str(d["version"]),
        seed=int(d["seed"]),
        periods=int(d["periods"]),
        min_periods=int(d["min_periods"]),
        small_tx_amount=float(d["small_tx_amount"]),
        clr_epsilon=float(d["clr_epsilon"]),
        trait_count=int(d["traits"]["count"]),
        trait_min_deviation=float(d["traits"]["min_deviation_percentile"]),
    )
