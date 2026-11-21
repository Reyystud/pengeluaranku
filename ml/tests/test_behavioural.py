"""Golden set integrity and the behavioural-test logic (PRD 21.4; T-26)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from ml.classification import behavioural
from ml.taxonomy import CATEGORIES, MODEL_LABELS

KNOBS = {
    "golden_min_accuracy": 0.95,
    "min_correct_share_per_category": 0.6667,
    "invariance_min_pass_rate": 0.90,
}


def test_fr_03_golden_set_has_100_cases_and_three_per_category() -> None:
    cases = behavioural.load_golden()
    assert len(cases) >= 100
    counts = Counter(c["label"] for c in cases)
    assert set(counts) == set(MODEL_LABELS)
    assert min(counts.values()) >= 3


def test_fr_03_golden_cases_are_valid_and_unique() -> None:
    types = {c.slug: c.transaction_type for c in CATEGORIES}
    seen = set()
    for case in behavioural.load_golden():
        assert case["type"] == types[case["label"]]
        assert case["payment_method"] in {
            "cash", "bank_transfer", "debit_card", "credit_card", "e_wallet", "qris", "other"
        }  # fmt: skip
        key = (case["description"], case["label"])
        assert key not in seen
        seen.add(key)
    behavioural.features_for(behavioural.load_golden())  # every case builds features


def test_fr_21_04_perturbations_change_text_but_not_meaning() -> None:
    case = {"description": "KOPI KENANGAN SENAYAN", "merchant": "Kopi Kenangan"}
    assert behavioural.typo(case)["description"] != case["description"]
    assert behavioural.typo({"description": "ab cd", "merchant": None})["merchant"] is None
    assert behavioural.reference_prefix(case)["description"] == "QRIS KOPI KENANGAN SENAYAN 839201"
    moved = behavioural.case_and_location(case)
    assert moved["description"] == "kopi kenangan senayan - BDG" and moved["merchant"] == (
        "kopi kenangan"
    )


def stub(monkeypatch: pytest.MonkeyPatch, wrong: set[str], flip_perturbed: bool = False) -> None:
    """Replace the model: right everywhere except ``wrong`` descriptions."""

    def fake(_art: Any, cases: list[dict[str, Any]]) -> list[str]:
        out = []
        for c in cases:
            bad = str(c["description"]) in wrong
            changed = flip_perturbed and (
                str(c["description"]).endswith("839201") or " - BDG" in str(c["description"])
            )
            out.append("other_expense" if bad or changed else str(c["label"]))
        return out

    monkeypatch.setattr(behavioural, "predict_top1", fake)


def test_fr_21_04_perfect_model_passes_every_check(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, set())
    result = behavioural.run_behavioural({}, KNOBS)
    assert result["golden_accuracy"] == 1.0 and all(result["checks"].values())
    assert result["golden_failures"] == []


def test_fr_21_04_golden_accuracy_threshold_and_failure_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = behavioural.load_golden()
    wrong = {str(c["description"]) for c in cases[:6] if c["label"] != "other_expense"}
    stub(monkeypatch, wrong)
    result = behavioural.run_behavioural({}, KNOBS)
    assert result["golden_accuracy"] < 1.0
    assert {f["description"] for f in result["golden_failures"]} == wrong


def test_fr_21_04_minimum_functionality_flags_the_category(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [c for c in behavioural.load_golden() if c["label"] == "refund"]
    stub(monkeypatch, {str(c["description"]) for c in cases[:3]})  # 3 of 6 wrong: share 0.5
    result = behavioural.run_behavioural({}, KNOBS)
    assert result["mft_failures"] == ["refund"]
    assert result["checks"]["minimum_functionality"] is False


def test_fr_21_04_invariance_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    stub(monkeypatch, set(), flip_perturbed=True)
    result = behavioural.run_behavioural({}, KNOBS)
    assert result["checks"]["invariance"] is False
    assert result["invariance_pass_rate"]["typo"] == 1.0  # typos were not flipped by the stub
