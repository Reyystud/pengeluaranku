"""Helpers shared by the ML service tests (imported by name; see conftest)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from ml_service.config import Settings

from ml.features import FEATURE_VERSION
from ml.taxonomy import MODEL_LABELS, TAXONOMY_VERSION

ROOT = Path(__file__).resolve().parents[3]
THRESHOLDS = {"t_high": 0.9, "t_low": 0.6, "calibration": "isotonic"}


def toy_rows() -> pd.DataFrame:
    rows = []
    for index, label in enumerate(MODEL_LABELS):
        words = label.replace("_", " ")
        for k in range(8):
            rows.append(
                {
                    "description": f"{words} shop {k}",
                    "merchant": None,
                    "amount": Decimal(10_000 * (index + 1) + k),
                    "type": "expense",
                    "payment_method": "e_wallet" if k % 2 else "cash",
                    "date": "2026-05-04 12:30" if k % 3 else "2026-05-05",
                    "label": label,
                }
            )
    return pd.DataFrame(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_model_dir(
    target: Path, artifacts: dict[str, Any], *, metadata: dict[str, Any] | None = None
) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {**artifacts, "labels": list(MODEL_LABELS), "feature_version": FEATURE_VERSION},
        target / "model.joblib",
    )
    meta: dict[str, Any] = {
        "model_name": "transaction-classifier",
        "feature_version": FEATURE_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "labels": list(MODEL_LABELS),
        "decision_thresholds": dict(THRESHOLDS),
        "artifact_sha256": {"model.joblib": sha256(target / "model.joblib")},
    }
    meta.update(metadata or {})
    (target / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return target


def classify_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "request_id": "req-1",
        "description": "food beverage shop 3",
        "merchant_key": "shop",
        "amount": "45000.00",
        "payment_method": "e_wallet",
        "transaction_type": "expense",
        "local_hour": 12,
        "weekday": 2,
        "feature_version": FEATURE_VERSION,
    }
    body.update(over)
    return body


def make_settings(models_dir: Path, **over: Any) -> Settings:
    return Settings(_env_file=None, model_source="local_dir", models_dir=models_dir, **over)
