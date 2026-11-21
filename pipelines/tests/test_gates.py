"""Promotion gates (PRD 16.3) and the model card text."""

from __future__ import annotations

from typing import Any

from pipelines import gates, model_card, registry
from pipelines.gates import GateInputs, Reference

KNOBS = {"max_ece": 0.05, "slice_max_drop_points": 5.0, "beats_production_margin_points": 0.5}
BEHAVIOURAL = {
    "golden_version": "golden-1",
    "n_cases": 114,
    "golden_accuracy": 0.97,
    "mft_failures": [],
    "invariance_pass_rate": {"typo": 0.95},
    "checks": {"golden_accuracy": True, "minimum_functionality": True, "invariance": True},
}
LATENCY = {"requests": 1000, "threads": 2, "p95_ms": 30.0, "slo_p95_ms": 200.0, "within_slo": True}
SLICES = {"archetype:student": 0.90, "category:food_beverage": 0.95}


def inputs(**over: Any) -> GateInputs:
    base: dict[str, Any] = {
        "dirty": False,
        "seed": 42,
        "winner": "logreg",
        "baseline": "logreg",
        "test_ece": 0.01,
        "test_macro_f1": 0.97,
        "split_hash": "s1",
        "slices": SLICES,
        "baseline_slices": SLICES,
        "behavioural": BEHAVIOURAL,
        "latency": LATENCY,
        "reference": None,
        "knobs": KNOBS,
    }
    return GateInputs(**{**base, **over})


def run(**over: Any) -> list[gates.GateResult]:
    return gates.run_gates(inputs(**over))


def status(results: list[gates.GateResult], name: str) -> str:
    return next(r.status for r in results if r.name == name)


def prod(**over: Any) -> Reference:
    base: dict[str, Any] = {
        "version": "3",
        "split_hash": "s1",
        "test_macro_f1": 0.95,
        "slices": SLICES,
        "golden_accuracy": 0.96,
    }
    return Reference(**{**base, **over})


def test_fr_16_03_clean_run_without_production_passes() -> None:
    results = run()
    assert gates.gate_outcome(results) == "passed"
    assert status(results, "beats_production") == "skipped"
    assert status(results, "slices") == "skipped"  # the baseline is the winner


def test_fr_16_03_dirty_tree_or_missing_seed_fails_reproducibility() -> None:
    assert status(run(dirty=True), "reproducibility") == "fail"
    assert status(run(seed=None), "reproducibility") == "fail"
    assert not gates.gates_passed(run(dirty=True))


def test_fr_16_03_ece_boundary() -> None:
    assert status(run(test_ece=0.0501), "calibration") == "fail"
    assert status(run(test_ece=0.05), "calibration") == "pass"


def test_fr_16_03_beats_production_needs_the_margin_on_the_same_split() -> None:
    assert status(run(reference=prod(test_macro_f1=0.965)), "beats_production") == "pass"
    assert status(run(reference=prod(test_macro_f1=0.966)), "beats_production") == "fail"
    other = run(reference=prod(split_hash="other"))
    assert status(other, "beats_production") == "skipped"  # not comparable


def test_fr_16_03_slice_drop_over_five_points_needs_review_not_failure() -> None:
    worse = {**SLICES, "category:food_beverage": 0.89}  # -6 points vs production
    results = run(slices=worse, reference=prod(test_macro_f1=0.90))
    assert status(results, "slices") == "review"
    assert gates.gate_outcome(results) == "needs_review"
    assert gates.gates_passed(results)  # registered, but not auto-promotable


def test_fr_16_03_slice_drop_of_exactly_five_points_is_allowed() -> None:
    edge = {**SLICES, "category:food_beverage": 0.90}  # -5.0 points
    assert status(run(slices=edge, reference=prod(test_macro_f1=0.90)), "slices") == "pass"


def test_fr_16_03_slices_use_baseline_when_a_challenger_wins_and_no_production() -> None:
    worse = {**SLICES, "archetype:student": 0.80}
    results = run(winner="lightgbm", slices=worse)
    assert status(results, "slices") == "review"
    assert "baseline logreg" in next(r.detail for r in results if r.name == "slices")


def test_fr_21_04_failed_behavioural_check_blocks() -> None:
    bad = {**BEHAVIOURAL, "checks": {**BEHAVIOURAL["checks"], "golden_accuracy": False}}
    bad["golden_accuracy"] = 0.78
    bad["mft_failures"] = ["refund"]
    results = run(behavioural=bad)
    assert status(results, "behavioural_tests") == "fail"
    detail = next(r.detail for r in results if r.name == "behavioural_tests")
    assert "golden_accuracy" in detail and "refund" in detail


def test_fr_21_04_golden_regression_against_production_blocks() -> None:
    lower = {**BEHAVIOURAL, "golden_accuracy": 0.955}
    results = run(behavioural=lower, reference=prod(golden_accuracy=0.96, test_macro_f1=0.90))
    assert status(results, "behavioural_tests") == "fail"
    same = run(behavioural=lower, reference=prod(golden_accuracy=0.955, test_macro_f1=0.90))
    assert status(same, "behavioural_tests") == "pass"


def test_fr_16_03_latency_over_slo_blocks() -> None:
    slow = {**LATENCY, "p95_ms": 250.0, "within_slo": False}
    assert status(run(latency=slow), "latency") == "fail"


def test_fr_16_03_slice_scores_skip_classes_without_support() -> None:
    test = {
        "by_archetype": {"student": {"macro_f1": 0.9}},
        "per_class": {"a": {"f1": 0.8, "support": 10}, "b": {"f1": 0.0, "support": 0}},
    }
    assert gates.slice_scores(test) == {"archetype:student": 0.9, "category:a": 0.8}


def test_fr_16_01_semantic_version_follows_registry_version() -> None:
    assert registry.semantic_version("7") == "0.7.0"


def test_fr_16_01_model_card_states_gates_behavioural_results_and_limits() -> None:
    res = {"macro_f1": 0.9, "accuracy": 0.95, "ece": 0.01}
    report = {
        "run_id": "r1",
        "git_commit": "abc",
        "feature_version": "features-1",
        "taxonomy_version": "taxonomy-1",
        "selection": {"winner": "logreg", "baseline": "logreg", "required_gain_points": 2.0},
        "dataset": {"version": "synthetic/v1", "split_hash": "s", "transactions_sha256": "t"},
        "models": {"logreg": {"test": res, "test_unseen_merchant": res}},
        "behavioural": BEHAVIOURAL,
        "latency_benchmark": {**LATENCY, "p50_ms": 20.0, "p99_ms": 40.0},
    }
    meta = {
        "model_name": "transaction-classifier",
        "labels": ["a", "b"],
        "trained_at": "now",
        "decision_thresholds": {"t_high": 0.9, "t_low": 0.9, "calibration": "isotonic"},
    }
    text = model_card.render_model_card(report, meta, run(), "runid", None)
    assert "not registered" in text and "| slices | skipped |" in text
    assert "Golden set (golden-1, 114 cases): accuracy 0.970" in text
    assert "P95 30.0 ms" in text and "written by the project team" in text
