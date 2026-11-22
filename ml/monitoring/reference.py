"""Reference data for drift reports, stored with the model it describes (PRD 18.3).

``reference/reference_sample.parquet``: up to 10 000 rows of the VALIDATION split (never the
training rows, whose predictions are over-confident) with the columns a prediction log carries:
``log_amount``, ``payment_method``, ``hour_bucket``, ``predicted_category``, ``confidence``.
``reference/merchants.json``: hashes of every merchant key of the TRAIN split, to measure the
share of unseen merchants in production.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.monitoring.hashing import merchant_hash

REFERENCE_DIR = "reference"
SAMPLE_FILE = "reference_sample.parquet"
MERCHANTS_FILE = "merchants.json"
SAMPLE_ROWS = 10_000
REFERENCE_COLUMNS = (
    "log_amount",
    "payment_method",
    "hour_bucket",
    "predicted_category",
    "confidence",
)


def build_reference(
    artifacts: dict[str, Any],
    labels: list[str],
    validation: pd.DataFrame,
    train: pd.DataFrame,
    *,
    seed: int = 42,
    rows: int = SAMPLE_ROWS,
) -> tuple[pd.DataFrame, list[str]]:
    """Sample frame and merchant-hash vocabulary for one trained model."""
    from ml.classification.pipeline import batched_scores

    frame = validation
    if len(frame) > rows:
        frame = frame.sample(n=rows, random_state=seed).sort_index()
    raw = batched_scores(artifacts["model"], artifacts["transformer"], frame)
    proba = artifacts["calibrator"].predict_proba(raw)
    top = proba.argmax(axis=1)
    sample = pd.DataFrame(
        {
            "log_amount": np.round(frame["log_amount"].to_numpy(dtype=float), 2),
            "payment_method": frame["payment_method"].to_numpy(),
            "hour_bucket": frame["hour_bucket"].to_numpy(),
            "predicted_category": [labels[i] for i in top],
            "confidence": proba.max(axis=1),
        }
    )
    hashes = {merchant_hash(str(k)) for k in train["merchant_key"].unique()}
    return sample.reset_index(drop=True), sorted(h for h in hashes if h)


def write_reference(model_dir: Path, sample: pd.DataFrame, merchants: list[str]) -> Path:
    out = model_dir / REFERENCE_DIR
    out.mkdir(exist_ok=True)
    sample.to_parquet(out / SAMPLE_FILE, index=False)
    (out / MERCHANTS_FILE).write_text(json.dumps(merchants), encoding="utf-8")
    return out


def load_reference(directory: Path) -> tuple[pd.DataFrame, set[str]]:
    """Read what ``write_reference`` wrote (``directory`` is the ``reference`` folder)."""
    sample = pd.read_parquet(directory / SAMPLE_FILE)
    merchants = set(json.loads((directory / MERCHANTS_FILE).read_text(encoding="utf-8")))
    return sample, merchants
