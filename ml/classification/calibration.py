"""One-vs-rest isotonic calibration, renormalized (PRD 9.2). Fitted on the validation split."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression

FloatArray = NDArray[np.float64]


class IsotonicOvR:
    """Calibrate class scores (probabilities or decision values) into probabilities."""

    def __init__(self) -> None:
        self._models: list[IsotonicRegression] = []

    def fit(self, scores: FloatArray, y: NDArray[np.int64]) -> IsotonicOvR:
        self._models = []
        for k in range(scores.shape[1]):
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(scores[:, k], (y == k).astype(np.float64))
            self._models.append(iso)
        return self

    def predict_proba(self, scores: FloatArray) -> FloatArray:
        if not self._models:
            raise RuntimeError("calibrator is not fitted")
        out = np.column_stack([m.predict(scores[:, k]) for k, m in enumerate(self._models)]).astype(
            np.float64
        )
        total = out.sum(axis=1, keepdims=True)
        zero = total[:, 0] <= 0
        out[zero] = 1.0 / out.shape[1]  # no class has support: uniform, i.e. low confidence
        total[zero] = 1.0
        return out / total
