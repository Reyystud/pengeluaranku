"""Behavioural tests of the classifier (PRD 21.4): golden set, minimum functionality, invariance.

Tests run on the fitted artifacts (transformer, model, calibrator) through the same feature code
as serving. The golden set is hand-labelled in ``ml/tests/golden/classifier.yaml``; nothing here
is tuned on model output.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from ml.classification.pipeline import batched_scores
from ml.features.classifier import FEATURE_COLUMNS, TransactionInput, online_features
from ml.taxonomy import MODEL_LABELS

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "tests" / "golden" / "classifier.yaml"
OCCURRED = datetime(2026, 3, 11, 12, 30)  # a Wednesday, midday; fixed so runs are comparable


def load_golden(path: Path | None = None) -> list[dict[str, Any]]:
    data = yaml.safe_load((path or GOLDEN_PATH).read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = data["cases"]
    return cases


def features_for(cases: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [
        online_features(
            TransactionInput(
                description=str(c["description"]),
                merchant=c.get("merchant"),
                amount=Decimal(str(c["amount"])),
                transaction_type=str(c["type"]),
                payment_method=str(c["payment_method"]),
                occurred=OCCURRED,
                has_time=True,
            )
        )
        for c in cases
    ]
    return pd.DataFrame(rows, columns=list(FEATURE_COLUMNS))


def predict_top1(artifacts: dict[str, Any], cases: list[dict[str, Any]]) -> list[str]:
    frame = features_for(cases)
    raw = batched_scores(artifacts["model"], artifacts["transformer"], frame)
    proba = artifacts["calibrator"].predict_proba(raw)
    return [MODEL_LABELS[int(i)] for i in np.argmax(proba, axis=1)]


# ---- perturbations (PRD 21.4 invariance rows) ------------------------------------------------


def _typo_word(text: str) -> str:
    """Drop the second-to-last letter of the longest alphabetic word (a one-character typo)."""
    words = re.findall(r"[A-Za-z]{5,}", text)
    if not words:
        return text
    word = max(words, key=len)
    return text.replace(word, word[:-2] + word[-1], 1)


def typo(case: dict[str, Any]) -> dict[str, Any]:
    merchant = case.get("merchant")
    return {
        **case,
        "description": _typo_word(str(case["description"])),
        "merchant": None if merchant is None else _typo_word(str(merchant)),
    }


def reference_prefix(case: dict[str, Any]) -> dict[str, Any]:
    return {**case, "description": f"QRIS {case['description']} 839201"}


def case_and_location(case: dict[str, Any]) -> dict[str, Any]:
    merchant = case.get("merchant")
    return {
        **case,
        "description": f"{str(case['description']).lower()} - BDG",
        "merchant": None if merchant is None else str(merchant).lower(),
    }


PERTURBATIONS = {
    "typo": typo,
    "reference_prefix": reference_prefix,
    "case_and_location": case_and_location,
}


def run_behavioural(
    artifacts: dict[str, Any], knobs: dict[str, Any], golden: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Golden accuracy, per-category minimum functionality and invariance pass rates."""
    cases = golden if golden is not None else load_golden()
    base = predict_top1(artifacts, cases)
    labels = [str(c["label"]) for c in cases]
    correct = [p == y for p, y in zip(base, labels, strict=True)]

    per_category: dict[str, dict[str, float]] = {}
    for label in sorted(set(labels)):
        hits = [ok for ok, y in zip(correct, labels, strict=True) if y == label]
        per_category[label] = {"n": len(hits), "correct_share": sum(hits) / len(hits)}
    min_share = float(knobs["min_correct_share_per_category"])
    mft_failures = sorted(k for k, v in per_category.items() if v["correct_share"] < min_share)

    invariance: dict[str, float] = {}
    for name, perturb in PERTURBATIONS.items():
        changed = predict_top1(artifacts, [perturb(c) for c in cases])
        invariance[name] = float(np.mean([a == b for a, b in zip(base, changed, strict=True)]))

    accuracy = float(np.mean(correct))
    min_inv = float(knobs["invariance_min_pass_rate"])
    return {
        "golden_version": "golden-1",
        "n_cases": len(cases),
        "golden_accuracy": accuracy,
        "golden_failures": [
            {"description": str(c["description"]), "label": y, "predicted": p}
            for c, y, p in zip(cases, labels, base, strict=True)
            if y != p
        ],
        "per_category": per_category,
        "mft_failures": mft_failures,
        "invariance_pass_rate": invariance,
        "checks": {
            "golden_accuracy": accuracy >= float(knobs["golden_min_accuracy"]),
            "minimum_functionality": not mft_failures,
            "invariance": all(v >= min_inv for v in invariance.values()),
        },
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m ml.classification.behavioural <run dir>``: golden/invariance + latency report."""
    import argparse
    import json

    import joblib

    from ml.classification.benchmark import latency_benchmark
    from ml.classification.config import load_train_config

    parser = argparse.ArgumentParser(prog="ml.classification.behavioural")
    parser.add_argument(
        "run_dir", type=Path, help="a models/transaction-classifier/<run> directory"
    )
    args = parser.parse_args(argv)
    cfg = load_train_config()
    artifacts = joblib.load(args.run_dir / "model.joblib")
    result = run_behavioural(artifacts, cfg["behavioural"])
    result["latency_benchmark"] = latency_benchmark(artifacts, cfg["benchmark"])
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
