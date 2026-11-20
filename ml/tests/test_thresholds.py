"""Tests for decision-threshold calibration (PRD 7.3.4; T-10). Confidences are hand-built."""

import numpy as np
import pytest

from ml.classification.config import load_train_config
from ml.classification.thresholds import build_report, choose_thresholds, decision_stats

PARAMS = {
    "high_precision_target": 0.95,
    "low_precision_target": 0.70,
    "band_width": 0.05,
    "min_band_support": 100,
    "defaults": {"t_high": 0.85, "t_low": 0.60},
}


def make(bands: list[tuple[float, int, float]]) -> tuple[np.ndarray, np.ndarray]:
    """bands = (confidence value, row count, precision) -> flat arrays (deterministic)."""
    conf, ok = [], []
    for value, n, precision in bands:
        correct = round(n * precision)
        conf += [value] * n
        ok += [True] * correct + [False] * (n - correct)
    return np.array(conf), np.array(ok)


def test_fr_03_t_high_stops_at_first_failing_band() -> None:
    # 0.90+ is perfect, 0.80 band 0.97, 0.70 band 0.80 (fails 0.95), 0.60 band 0.75
    conf, ok = make([(0.97, 500, 1.0), (0.82, 300, 0.97), (0.72, 200, 0.80), (0.62, 200, 0.75)])
    out = choose_thresholds(conf, ok, PARAMS)
    assert out["t_high"] == 0.80
    assert out["t_low"] == 0.60  # bands 0.70 and 0.60 reach 0.70 precision
    assert out["flags"] == []


def test_fr_03_degenerate_cumulative_case_is_not_degenerate_with_bands() -> None:
    """Overall precision is above target, yet the weak band must stay below t_high."""
    conf, ok = make([(0.97, 9000, 1.0), (0.52, 1000, 0.50)])  # overall 0.95
    out = choose_thresholds(conf, ok, PARAMS)
    assert out["t_high"] == 0.95  # only the band that really is precise
    assert out["t_low"] == 0.95
    assert any("no_suggest_band" in f for f in out["flags"])


def test_fr_03_suggest_band_empty_flag_when_band_below_fails_low_target() -> None:
    conf, ok = make([(0.97, 500, 1.0), (0.82, 300, 0.99), (0.72, 300, 0.50)])
    out = choose_thresholds(conf, ok, PARAMS)
    assert out["t_high"] == 0.80
    assert out["t_low"] == 0.80
    assert any("no_suggest_band" in f for f in out["flags"])


def test_fr_03_defaults_used_when_top_band_fails() -> None:
    conf, ok = make([(0.97, 500, 0.80), (0.72, 300, 0.60)])
    out = choose_thresholds(conf, ok, PARAMS)
    assert out["t_high"] == 0.85
    assert "t_high_not_found_used_default" in out["flags"]


def test_fr_03_unsupported_bands_are_ignored() -> None:
    # a 30-row band with 0% precision must not block lowering the threshold
    conf, ok = make([(0.97, 500, 1.0), (0.87, 30, 0.0), (0.77, 400, 0.99)])
    assert choose_thresholds(conf, ok, PARAMS)["t_high"] == 0.75


def test_fr_03_confidence_exactly_one_is_in_the_top_band() -> None:
    conf, ok = make([(1.0, 300, 1.0)])
    assert choose_thresholds(conf, ok, PARAMS)["t_high"] == 0.95


def test_fr_03_decision_stats_partition_rows() -> None:
    conf = np.array([0.9, 0.9, 0.7, 0.7, 0.3, 0.3])
    ok = np.array([True, True, True, False, False, True])
    s = decision_stats(conf, ok, t_high=0.85, t_low=0.60)
    assert s["auto_apply"] == {"share": pytest.approx(1 / 3), "precision": 1.0}
    assert s["suggest"] == {"share": pytest.approx(1 / 3), "precision": 0.5}
    assert s["needs_review"] == {"share": pytest.approx(1 / 3), "precision": 0.5}


def test_fr_03_thresholds_chosen_on_validation_only() -> None:
    val = make([(0.97, 500, 1.0), (0.52, 500, 0.50)])
    other = make([(0.97, 500, 0.10)])  # would fail everything if it were used
    report = build_report({"validation": val, "test": other}, PARAMS)
    assert report["decision_thresholds"]["chosen_on"] == "validation"
    assert report["decision_thresholds"]["t_high"] == 0.95
    assert report["decision_stats"]["test"]["auto_apply"]["precision"] == pytest.approx(0.10)


def test_fr_03_config_defines_thresholds_section() -> None:
    cfg = load_train_config()["thresholds"]
    assert set(cfg) >= {"high_precision_target", "low_precision_target", "band_width", "defaults"}
