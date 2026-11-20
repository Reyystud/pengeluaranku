"""Classifier inference: request -> features (shared with training) -> calibrated decision."""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
import pandas as pd

from ml.features.classifier import FEATURE_COLUMNS, features_from_parts
from ml_service.loading.artifact import LoadedClassifier
from ml_service.schemas import Alternative, ClassifyRequest, ClassifyResponse, Thresholds

TOP_ALTERNATIVES = 2  # top-1 plus two alternatives (PRD 7.3 FR-03.02: top-3)


def decide(confidence: float, t_high: float, t_low: float) -> str:
    """auto_apply >= t_high; suggest in [t_low, t_high); otherwise needs_review (PRD 7.3.4)."""
    if confidence >= t_high:
        return "auto_apply"
    if confidence >= t_low:
        return "suggest"
    return "needs_review"


def feature_frame(requests: Sequence[ClassifyRequest]) -> pd.DataFrame:
    rows = [
        features_from_parts(
            description=r.description,
            merchant_key=r.merchant_key,
            amount=r.amount,
            payment_method=r.payment_method,
            transaction_type=r.transaction_type,
            local_hour=r.local_hour,
            weekday=r.weekday,
        )
        for r in requests
    ]
    return pd.DataFrame(rows, columns=list(FEATURE_COLUMNS))


def classify(
    model: LoadedClassifier, requests: Sequence[ClassifyRequest]
) -> list[ClassifyResponse]:
    started = time.perf_counter()
    frame = feature_frame(requests)
    X = model.transformer.transform(frame).tocsr()
    if hasattr(model.model, "predict_proba"):
        raw = np.asarray(model.model.predict_proba(X), dtype=np.float64)
    else:
        raw = np.asarray(model.model.decision_function(X), dtype=np.float64)
    proba = model.calibrator.predict_proba(raw)
    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

    thresholds = Thresholds(t_high=model.t_high, t_low=model.t_low)
    out: list[ClassifyResponse] = []
    for row in proba:
        order = np.argsort(-row, kind="stable")[: 1 + TOP_ALTERNATIVES]
        top = int(order[0])
        confidence = float(row[top])
        out.append(
            ClassifyResponse(
                predicted_category=model.labels[top],
                confidence=round(confidence, 6),
                decision=decide(confidence, model.t_high, model.t_low),  # type: ignore[arg-type]
                alternatives=[
                    Alternative(category=model.labels[int(i)], confidence=round(float(row[i]), 6))
                    for i in order[1:]
                ],
                model_version=model.label,
                feature_version=model.feature_version,
                thresholds=thresholds,
                latency_ms=latency_ms,
            )
        )
    return out
