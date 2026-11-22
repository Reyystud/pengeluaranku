"""K-Means behavior clusterer: fit, assign, traits, and a YAML-friendly artifact (PRD 9.5, FR-13).

The artifact (``config/clusterer_model.yaml``) holds everything assignment needs and nothing about
any user: imputation values, standardization, centroids, and per-segment deciles of each raw
feature (for the "more than 70% of similar users" traits). Segment names and descriptions are
written into it by a person after inspecting the centroids (FR-13.03).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from ml.clustering.config import ClusteringConfig
from ml.clustering.features import MODEL_COLUMNS, RAW_COLUMNS, model_matrix

DECILES = tuple(range(0, 101, 10))
STD_FLOOR = 1e-9


@dataclass
class Segment:
    id: str
    name: str = ""
    description: str = ""
    size: int = 0
    deciles: dict[str, list[float]] = field(default_factory=dict)


@dataclass
class Clusterer:
    version: str
    impute: dict[str, float]
    mean: list[float]
    std: list[float]
    centroids: list[list[float]]
    segments: list[Segment]

    def space(self, raw: pd.DataFrame, cfg: ClusteringConfig) -> np.ndarray:
        """Standardized model-space matrix of ``raw`` (missing values imputed)."""
        m = model_matrix(raw, cfg)
        for col, value in self.impute.items():
            m[col] = m[col].fillna(value)
        x = m[list(MODEL_COLUMNS)].to_numpy(dtype=float)
        return (x - np.asarray(self.mean)) / np.asarray(self.std)

    def assign(self, raw: pd.DataFrame, cfg: ClusteringConfig) -> tuple[np.ndarray, np.ndarray]:
        """(segment index, distance to its centroid) per row."""
        x = self.space(raw, cfg)
        c = np.asarray(self.centroids)
        dist = np.linalg.norm(x[:, None, :] - c[None, :, :], axis=2)
        return dist.argmin(axis=1), dist.min(axis=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "impute": self.impute,
            "mean": self.mean,
            "std": self.std,
            "centroids": self.centroids,
            "segments": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "size": s.size,
                    "deciles": s.deciles,
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Clusterer:
        return cls(
            version=str(d["version"]),
            impute={k: float(v) for k, v in d["impute"].items()},
            mean=[float(v) for v in d["mean"]],
            std=[float(v) for v in d["std"]],
            centroids=[[float(v) for v in row] for row in d["centroids"]],
            segments=[
                Segment(
                    str(s["id"]),
                    str(s.get("name", "")),
                    str(s.get("description", "")),
                    int(s.get("size", 0)),
                    {k: [float(x) for x in v] for k, v in s.get("deciles", {}).items()},
                )
                for s in d["segments"]
            ],
        )


def prepare(
    raw: pd.DataFrame, cfg: ClusteringConfig
) -> tuple[np.ndarray, dict[str, float], list[float], list[float]]:
    """Impute with medians, standardize: (X, impute, mean, std)."""
    m = model_matrix(raw, cfg)
    impute = {c: float(m[c].median()) for c in MODEL_COLUMNS if m[c].isna().any()}
    for col, value in impute.items():
        m[col] = m[col].fillna(value)
    x = m[list(MODEL_COLUMNS)].to_numpy(dtype=float)
    mean = x.mean(axis=0)
    std = np.maximum(x.std(axis=0), STD_FLOOR)
    return (x - mean) / std, impute, mean.tolist(), std.tolist()


def fit(
    raw: pd.DataFrame, k: int, cfg: ClusteringConfig, version: str, n_init: int = 10
) -> Clusterer:
    x, impute, mean, std = prepare(raw, cfg)
    km = KMeans(n_clusters=k, n_init=n_init, random_state=cfg.seed).fit(x)
    segments = []
    for j in range(k):
        members = raw[km.labels_ == j]
        deciles = {
            col: [float(v) for v in np.nanpercentile(members[col].to_numpy(dtype=float), DECILES)]
            for col in RAW_COLUMNS
            if members[col].notna().any()
        }
        segments.append(Segment(id=f"segment-{j}", size=len(members), deciles=deciles))
    return Clusterer(version, impute, mean, std, km.cluster_centers_.tolist(), segments)


def percentile_in(value: float, deciles: list[float]) -> float:
    """Percentile rank (0-100) of ``value`` among the segment members, from their deciles."""
    q = np.asarray(deciles)
    if value <= q[0]:
        return 0.0 if value < q[0] else 100.0 * float(np.mean(q <= value)) / 2
    if value >= q[-1]:
        return 100.0 if value > q[-1] else 100.0 - 100.0 * float(np.mean(q >= value)) / 2
    return float(np.interp(value, q, np.asarray(DECILES, dtype=float)))


def traits(
    raw_row: dict[str, float], segment: Segment, cfg: ClusteringConfig
) -> list[dict[str, Any]]:
    """Up to ``cfg.trait_count`` features where the user stands out among similar users.

    Each trait: ``feature``, ``value`` (raw), ``direction`` (``higher``/``lower``) and ``percent``
    (the user is higher/lower than this percent of the segment's members). Features within
    ``cfg.trait_min_deviation`` percentile points of the middle are not traits.
    """
    scored = []
    for feature, deciles in segment.deciles.items():
        value = raw_row.get(feature)
        if value is None or np.isnan(value):
            continue
        p = percentile_in(float(value), deciles)
        scored.append((abs(p - 50.0), feature, float(value), p))
    scored.sort(key=lambda t: (-t[0], t[1]))
    out: list[dict[str, Any]] = []
    for deviation, feature, value, p in scored:
        if deviation < cfg.trait_min_deviation or len(out) >= cfg.trait_count:
            break
        higher = p >= 50.0
        out.append(
            {
                "feature": feature,
                "value": round(value, 4),
                "direction": "higher" if higher else "lower",
                "percent": round(p if higher else 100.0 - p),
            }
        )
    return out
