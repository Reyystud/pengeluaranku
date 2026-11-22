"""T-35: reference sample stored with the model (PRD 18.3)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse

from ml.monitoring import (
    REFERENCE_COLUMNS,
    build_reference,
    load_reference,
    merchant_hash,
    write_reference,
)


class _Transformer:
    def transform(self, frame: pd.DataFrame) -> Any:
        return sparse.csr_matrix(frame[["log_amount"]].to_numpy())


class _Model:
    def predict_proba(self, X: Any) -> np.ndarray:
        x = X.toarray()[:, 0]
        p = 1 / (1 + np.exp(-(x - 10)))
        return np.column_stack([1 - p, p])


class _Calibrator:
    def predict_proba(self, raw: np.ndarray) -> np.ndarray:
        return raw


def _frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "log_amount": rng.normal(10, 1, n),
            "payment_method": rng.choice(["cash", "e_wallet"], n),
            "hour_bucket": rng.choice(["morning", "midday"], n),
            "merchant_key": rng.choice(["gojek", "tokopedia", "indomaret"], n),
        }
    )


def test_fr_18_03_reference_has_the_log_columns_and_is_capped_and_reproducible() -> None:
    art = {"transformer": _Transformer(), "model": _Model(), "calibrator": _Calibrator()}
    args = (art, ["food_beverage", "transport"], _frame(500, 1), _frame(300, 2))
    a, merchants = build_reference(*args, rows=120, seed=7)
    b, _ = build_reference(*args, rows=120, seed=7)
    assert list(a.columns) == list(REFERENCE_COLUMNS)
    assert len(a) == 120 and a.equals(b)
    assert set(a["predicted_category"]) <= {"food_beverage", "transport"}
    assert a["confidence"].between(0.5, 1.0).all()
    assert merchants == sorted({merchant_hash(k) for k in ("gojek", "tokopedia", "indomaret")})


def test_fr_18_03_reference_uses_validation_rows_not_training_rows(tmp_path: Any) -> None:
    art = {"transformer": _Transformer(), "model": _Model(), "calibrator": _Calibrator()}
    validation, train = _frame(50, 1), _frame(50, 2)
    validation["log_amount"] += 100  # unmistakably different from train
    sample, _ = build_reference(art, ["a", "b"], validation, train)
    assert sample["log_amount"].min() > 50
    folder = write_reference(tmp_path, sample, ["abc"])
    loaded, known = load_reference(folder)
    assert len(loaded) == 50 and known == {"abc"}
