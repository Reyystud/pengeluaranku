"""Anomaly model experiment (PRD 7.6.3, 9.3): features, no leakage, threshold choice, gate."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ml.anomaly_detection import load_anomaly_config
from ml.anomaly_detection.model_features import FEATURES, user_features
from ml.anomaly_detection.model_train import at_threshold, best_threshold, gate
from ml.anomaly_detection.stats import mad, median

CFG = load_anomaly_config()


def user_rows(n: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    start = pd.Timestamp("2025-01-01 12:00")
    rows = []
    for i in range(n):
        rows.append(
            {
                "occurred_at": start + pd.Timedelta(hours=7 * i),
                "type": "expense",
                "amount_f": float(rng.integers(20, 60)) * 1000,
                "category": "food_beverage" if i % 3 else "groceries",
                "merchant_key": f"m{i % 4}",
                "has_time": True,
            }
        )
    rows.append(
        {
            "occurred_at": start + pd.Timedelta(hours=100),
            "type": "income",
            "amount_f": 5e6,
            "category": "salary",
            "merchant_key": "boss",
            "has_time": True,
        }
    )
    frame = pd.DataFrame(rows).sort_values("occurred_at", kind="stable").reset_index(drop=True)
    return frame


def feats(frame: pd.DataFrame) -> pd.DataFrame:
    return user_features(frame, CFG, {}, CFG.min_category_history)


def test_fr_06_03_features_are_point_in_time() -> None:
    frame = user_rows()
    cut = 50
    before = feats(frame.iloc[:cut])
    future = frame.iloc[cut:].copy()
    future["amount_f"] = future["amount_f"] * 1000 + 99  # any leak would change the numbers
    after = feats(pd.concat([frame.iloc[:cut], future], ignore_index=True)).iloc[: len(before)]
    pd.testing.assert_frame_equal(before, after.set_index(before.index), check_exact=True)


def test_fr_06_03_z_cat_is_the_modified_z_of_the_prior_history() -> None:
    frame = user_rows()
    out = feats(frame)
    i = int(out.index[-1])
    row = frame.loc[i]
    prior = frame[
        (frame["occurred_at"] < row["occurred_at"])
        & (frame["type"] == "expense")
        & (frame["category"] == row["category"])
    ]
    logs = np.log1p(prior["amount_f"]).tolist()
    m = median(logs)
    expected = CFG.z_scale * (math.log1p(row["amount_f"]) - m) / max(mad(logs), CFG.mad_floor)
    assert math.isclose(out.loc[i, "z_cat"], expected, rel_tol=1e-9)
    assert out.loc[i, "history_n_cat"] == len(prior)


def test_fr_06_03_features_cover_the_documented_columns_and_expenses_only() -> None:
    out = feats(user_rows())
    assert list(out.columns) == [*FEATURES, "base_typ"]
    assert len(out) == 80  # the income row gets no features
    assert out.isna().sum().sum() == 0
    assert out["days_since_income"].iloc[0] == 400.0  # no income yet


def test_fr_06_03_threshold_maximizes_precision_subject_to_recall() -> None:
    y = np.array([1, 1, 0, 1, 0, 0, 0, 0])
    score = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2])
    thr = best_threshold(y, score, 0.5)
    assert thr == 0.8  # flags two rows, both positives: precision 1.0, recall 2/3
    res = at_threshold(y, score, thr)
    assert (res["flagged"], res["tp"], res["precision"]) == (2, 2, 1.0)
    assert best_threshold(np.zeros(4, dtype=int), np.arange(4.0), 0.5) is None


def test_fr_06_03_gate_requires_a_better_precision_and_the_recall_target() -> None:
    def result(
        model_p: float | None, model_r: float | None, base_p: float
    ) -> dict[str, dict[str, dict[str, dict[str, float | None]]]]:
        return {
            "baseline": {"amount_spike": {"test": {"precision": base_p, "recall": 0.6}}},
            "lof": {"amount_spike": {"test": {"precision": model_p, "recall": model_r}}},
        }

    assert gate(result(0.3, 0.6, 0.2), "lof", 0.0, 0.5)["beats_baseline"]
    assert not gate(result(0.2, 0.6, 0.2), "lof", 0.0, 0.5)["beats_baseline"]
    assert not gate(result(0.3, 0.4, 0.2), "lof", 0.0, 0.5)["beats_baseline"]  # recall below target
    assert not gate(result(None, 0.0, 0.2), "lof", 0.0, 0.5)["beats_baseline"]
