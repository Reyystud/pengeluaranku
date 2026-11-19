"""Evaluation metrics for the classifier (PRD 9.2, 9.6)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]


def expected_calibration_error(proba: FloatArray, y: IntArray, bins: int = 15) -> float:
    """ECE of the top-1 prediction with equal-width confidence bins."""
    conf = proba.max(axis=1)
    correct = (proba.argmax(axis=1) == y).astype(np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    index = np.clip(np.digitize(conf, edges[1:-1], right=True), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = index == b
        if mask.any():
            total += mask.mean() * abs(correct[mask].mean() - conf[mask].mean())
    return float(total)


def coverage_curve(
    proba: FloatArray, y: IntArray, thresholds: list[float]
) -> list[dict[str, float]]:
    """Share of rows auto-applied (confidence >= t) and the precision among them."""
    conf = proba.max(axis=1)
    correct = proba.argmax(axis=1) == y
    rows = []
    for t in thresholds:
        mask = conf >= t
        rows.append(
            {
                "threshold": float(t),
                "coverage": float(mask.mean()),
                "precision": float(correct[mask].mean()) if mask.any() else float("nan"),
            }
        )
    return rows


def summarize(proba: FloatArray, y: IntArray, labels: list[str], ece_bins: int) -> dict[str, Any]:
    pred = proba.argmax(axis=1)
    ids = list(range(len(labels)))
    p, r, f, support = precision_recall_fscore_support(y, pred, labels=ids, zero_division=0)
    per_class = {
        labels[i]: {
            "precision": float(p[i]),
            "recall": float(r[i]),
            "f1": float(f[i]),
            "support": int(support[i]),
        }
        for i in ids
    }
    present = [i for i in ids if support[i] > 0]
    return {
        "n": int(len(y)),
        "accuracy": float((pred == y).mean()),
        "macro_f1": float(f1_score(y, pred, labels=present, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, pred, labels=ids, average="weighted", zero_division=0)),
        "ece": expected_calibration_error(proba, y, ece_bins),
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(y, pred, labels=ids).tolist(),
    }


def slice_metrics(
    proba: FloatArray, y: IntArray, groups: pd.Series, labels: list[str]
) -> dict[str, dict[str, float]]:
    pred = proba.argmax(axis=1)
    out: dict[str, dict[str, float]] = {}
    for name, idx in groups.groupby(groups).indices.items():
        ids = np.asarray(idx)
        present = sorted(set(y[ids]))
        out[str(name)] = {
            "n": float(len(ids)),
            "accuracy": float((pred[ids] == y[ids]).mean()),
            "macro_f1": float(
                f1_score(y[ids], pred[ids], labels=present, average="macro", zero_division=0)
            ),
        }
    return out


def confident_errors(
    proba: FloatArray, y: IntArray, frame: pd.DataFrame, labels: list[str], top: int
) -> list[dict[str, Any]]:
    """The ``top`` most confident wrong predictions (synthetic data, so descriptions are safe)."""
    pred = proba.argmax(axis=1)
    conf = proba.max(axis=1)
    wrong = np.flatnonzero(pred != y)
    order = wrong[np.argsort(-conf[wrong])][:top]
    return [
        {
            "description": str(frame["description"].iloc[i]),
            "true_merchant": str(frame["true_merchant"].iloc[i]),
            "true": labels[int(y[i])],
            "predicted": labels[int(pred[i])],
            "confidence": float(conf[i]),
            "amount_log1p": float(frame["log_amount"].iloc[i]),
        }
        for i in order
    ]
