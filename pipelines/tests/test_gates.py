"""Promotion gates that run in T-25 (PRD 16.3) and the model card text."""

from __future__ import annotations

from typing import Any

from pipelines import gates, model_card, registry

SELECTION = {"winner": "logreg", "baseline": "logreg", "required_gain_points": 2.0}


def run(**over: Any) -> list[gates.GateResult]:
    args: dict[str, Any] = {
        "dirty": False,
        "seed": 42,
        "winner": "logreg",
        "baseline": "logreg",
        "selection": SELECTION,
        "test_ece": 0.01,
        "max_ece": 0.05,
    }
    return gates.run_gates(**{**args, **over})


def status(results: list[gates.GateResult], name: str) -> str:
    return next(r.status for r in results if r.name == name)


def test_fr_16_03_clean_calibrated_run_passes() -> None:
    results = run()
    assert gates.gates_passed(results)
    assert status(results, "reproducibility") == "pass"


def test_fr_16_03_dirty_tree_fails_reproducibility() -> None:
    results = run(dirty=True)
    assert status(results, "reproducibility") == "fail" and not gates.gates_passed(results)


def test_fr_16_03_missing_seed_fails_reproducibility() -> None:
    assert status(run(seed=None), "reproducibility") == "fail"


def test_fr_16_03_ece_above_limit_fails_and_equal_passes() -> None:
    assert status(run(test_ece=0.0501), "calibration") == "fail"
    assert status(run(test_ece=0.05), "calibration") == "pass"


def test_fr_16_03_later_gates_are_listed_as_skipped_not_passed() -> None:
    results = run()
    skipped = {r.name for r in results if r.status == "skipped"}
    assert skipped == set(gates.DEFERRED)


def test_fr_16_01_semantic_version_follows_registry_version() -> None:
    assert registry.semantic_version("7") == "0.7.0"


def test_fr_16_01_model_card_states_gate_status_and_data_limits() -> None:
    res = {"macro_f1": 0.9, "accuracy": 0.95, "ece": 0.01}
    report = {
        "run_id": "r1",
        "git_commit": "abc",
        "feature_version": "features-1",
        "taxonomy_version": "taxonomy-1",
        "selection": SELECTION,
        "dataset": {"version": "synthetic/v1", "split_hash": "s", "transactions_sha256": "t"},
        "models": {"logreg": {"test": res, "test_unseen_merchant": res}},
    }
    meta = {
        "model_name": "transaction-classifier",
        "labels": ["a", "b"],
        "trained_at": "now",
        "decision_thresholds": {"t_high": 0.9, "t_low": 0.9, "calibration": "isotonic"},
    }
    text = model_card.render_model_card(report, meta, run(), "runid", None)
    assert "not registered" in text and "| slices | skipped |" in text
    assert "Synthetic data only" in text
