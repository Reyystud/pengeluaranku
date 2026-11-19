"""Tests for calibration and evaluation metrics (PRD 9.2; T-09). Values computed by hand."""

import numpy as np
import pandas as pd
import pytest

from ml.classification.calibration import IsotonicOvR
from ml.classification.data import cap_per_class
from ml.classification.metrics import (
    confident_errors,
    coverage_curve,
    expected_calibration_error,
    slice_metrics,
    summarize,
)


def test_ece_is_zero_for_perfectly_calibrated_confidences() -> None:
    # 10 rows at confidence 0.8, 8 correct -> gap 0
    proba = np.tile([0.8, 0.2], (10, 1))
    y = np.array([0] * 8 + [1] * 2)
    assert expected_calibration_error(proba, y, bins=15) == pytest.approx(0.0)


def test_ece_overconfident_model() -> None:
    # confidence 1.0, accuracy 0.5 -> ECE 0.5
    proba = np.tile([1.0, 0.0], (10, 1))
    y = np.array([0] * 5 + [1] * 5)
    assert expected_calibration_error(proba, y, bins=15) == pytest.approx(0.5)


def test_ece_confidence_one_falls_in_last_bin() -> None:
    proba = np.array([[1.0, 0.0]])
    assert expected_calibration_error(proba, np.array([0]), bins=15) == pytest.approx(0.0)


def test_coverage_curve_values() -> None:
    proba = np.array([[0.9, 0.1], [0.6, 0.4], [0.3, 0.7], [0.55, 0.45]])
    y = np.array([0, 1, 1, 0])  # predictions: 0, 0, 1, 0 -> correct: T, F, T, T
    curve = coverage_curve(proba, y, [0.5, 0.65, 0.95])
    assert curve[0] == {"threshold": 0.5, "coverage": 1.0, "precision": 0.75}
    assert curve[1]["coverage"] == 0.5 and curve[1]["precision"] == 1.0  # 0.9 and 0.7
    assert curve[2]["coverage"] == 0.0 and np.isnan(curve[2]["precision"])


def test_summarize_macro_f1_ignores_absent_classes_and_counts_support() -> None:
    labels = ["a", "b", "c"]
    proba = np.array([[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 1, 0]], dtype=float)
    y = np.array([0, 0, 1, 0])  # class c absent
    s = summarize(proba, y, labels, 15)
    assert s["accuracy"] == pytest.approx(0.75)
    # class a: P=1, R=2/3 -> F1=0.8 ; class b: P=0.5, R=1 -> F1=2/3 ; macro over present = 0.7333
    assert s["macro_f1"] == pytest.approx((0.8 + 2 / 3) / 2)
    assert s["per_class"]["c"]["support"] == 0
    assert s["confusion_matrix"][0] == [2, 1, 0]


def test_slice_metrics_per_group() -> None:
    proba = np.array([[1, 0], [1, 0], [0, 1], [1, 0]], dtype=float)
    y = np.array([0, 1, 1, 1])
    groups = pd.Series(["x", "x", "y", "y"])
    out = slice_metrics(proba, y, groups, ["a", "b"])
    assert out["x"]["accuracy"] == pytest.approx(0.5)
    assert out["y"]["accuracy"] == pytest.approx(0.5)


def test_confident_errors_are_sorted_and_limited() -> None:
    proba = np.array([[0.6, 0.4], [0.99, 0.01], [0.8, 0.2], [0.1, 0.9]])
    y = np.array([1, 1, 1, 1])  # first three wrong
    frame = pd.DataFrame(
        {
            "description": list("abcd"),
            "true_merchant": list("wxyz"),
            "log_amount": [1.0, 2.0, 3.0, 4.0],
        }
    )
    errors = confident_errors(proba, y, frame, ["l0", "l1"], top=2)
    assert [e["description"] for e in errors] == ["b", "c"]
    assert errors[0]["predicted"] == "l0" and errors[0]["true"] == "l1"


def test_isotonic_ovr_outputs_normalized_probabilities() -> None:
    rng = np.random.default_rng(0)
    scores = rng.random((200, 3))
    y = scores.argmax(axis=1)
    cal = IsotonicOvR().fit(scores, y)
    proba = cal.predict_proba(rng.random((50, 3)))
    assert proba.shape == (50, 3)
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert (proba >= 0).all()


def test_isotonic_ovr_fixes_overconfident_scores() -> None:
    # scores say 0.95 but the class is right only half the time
    scores = np.tile([0.95, 0.05], (200, 1))
    y = np.array([0, 1] * 100)
    proba = IsotonicOvR().fit(scores, y).predict_proba(scores)
    assert proba.max(axis=1).mean() == pytest.approx(0.5, abs=0.01)


def test_isotonic_requires_fit() -> None:
    with pytest.raises(RuntimeError):
        IsotonicOvR().predict_proba(np.zeros((1, 2)))


def test_cap_per_class_keeps_rare_classes_and_is_deterministic() -> None:
    frame = pd.DataFrame({"label": ["a"] * 100 + ["b"] * 3, "v": range(103)})
    one = cap_per_class(frame, 10, seed=1)
    two = cap_per_class(frame, 10, seed=1)
    assert one.equals(two)
    counts = one["label"].value_counts()
    assert counts["a"] == 10 and counts["b"] == 3
    assert not cap_per_class(frame, 10, seed=2).equals(one)
