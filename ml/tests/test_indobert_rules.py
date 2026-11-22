"""IndoBERT experiment (PRD 9.1, 9.2): the pure parts, without torch."""

from __future__ import annotations

import numpy as np

from ml.classification.indobert import build_text, decide, fit_temperature, softmax
from ml.config import _load_yaml

RULE = _load_yaml("train/indobert.yaml")["ship_rule"]


def report(bert_f1: float, base_f1: float, p95: float | None = None, rss: float = 1.0) -> dict:  # type: ignore[type-arg]
    out: dict = {  # type: ignore[type-arg]
        "bert": {"test": {"macro_f1": bert_f1}},
        "baseline": {"test": {"macro_f1": base_f1}},
    }
    if p95 is not None:
        out["profile"] = {"fp32": {"p95_ms": p95, "rss_after_inference_gib": rss}}
    return out


def test_fr_03_ship_rule_needs_two_points_and_latency_and_ram() -> None:
    assert RULE["min_macro_f1_gain_points"] == 2.0  # fixed before training (PRD 9.1)
    assert decide(report(0.91, 0.90), RULE)["f1_ok"] is False  # +1.0 point
    assert decide(report(0.921, 0.90), RULE)["f1_ok"] is True  # +2.1 points
    assert decide(report(0.95, 0.90), RULE)["ship"] is None  # latency not measured yet
    assert decide(report(0.95, 0.90, p95=300.0), RULE)["ship"] is True
    assert decide(report(0.95, 0.90, p95=700.0), RULE)["ship"] is False  # over the 500 ms SLO
    assert decide(report(0.95, 0.90, p95=300.0, rss=2.5), RULE)["ship"] is False  # over 2 GiB
    assert decide(report(0.90, 0.90, p95=100.0), RULE)["ship"] is False  # fast but no better


def test_fr_03_temperature_is_one_for_calibrated_logits_and_above_one_for_overconfident() -> None:
    rng = np.random.default_rng(0)
    n, k = 4000, 5
    logits = rng.normal(size=(n, k))
    y = np.array([rng.choice(k, p=p) for p in softmax(logits)])  # labels drawn from the model
    assert abs(fit_temperature(logits, y) - 1.0) < 0.15
    assert fit_temperature(logits * 3.0, y) > 2.0  # the same model made overconfident


def test_fr_03_softmax_rows_sum_to_one_and_temperature_softens() -> None:
    z = np.array([[4.0, 1.0, 0.0]])
    assert np.isclose(softmax(z).sum(), 1.0)
    assert softmax(z, 3.0).max() < softmax(z).max()


def test_fr_03_model_text_has_no_amount_and_skips_empty_parts() -> None:
    assert build_text("Beli kopi ", "Starbucks", "e_wallet") == "Beli kopi | Starbucks | e wallet"
    assert build_text("Beli kopi", None, "cash") == "Beli kopi | cash"
