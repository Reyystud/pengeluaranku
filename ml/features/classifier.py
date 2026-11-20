"""Classifier features that are computed per transaction (PRD 11.2.1).

Two code paths exist on purpose and MUST agree (PRD 11.1 rule 3, tested in
``ml/tests/test_feature_parity.py``):

* ``build_feature_frame``: vectorized pandas path used by the training pipeline.
* ``online_features``: single-transaction path used by the backend and the ML service.

Text vectorizers (TF-IDF) and the amount standardizer are fitted in training (T-09) from the
columns produced here; their fitted state lives in the model artifact, not in this module.
Nothing here looks at other rows, so these features cannot leak across users or time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from ml.preprocessing import preprocess_description, resolve_merchant

HOUR_BUCKETS = ("night", "morning", "midday", "afternoon", "evening", "unknown")
FEATURE_COLUMNS = (
    "text",
    "merchant_key",
    "log_amount",
    "payment_method",
    "transaction_type",
    "hour_bucket",
    "is_weekend",
)
INPUT_COLUMNS = ("description", "merchant", "amount", "type", "payment_method", "date")


@dataclass(frozen=True)
class TransactionInput:
    """One transaction as the classifier sees it. ``occurred`` is the user's local time."""

    description: str
    merchant: str | None
    amount: Decimal
    transaction_type: str
    payment_method: str
    occurred: datetime
    has_time: bool


def hour_bucket(hour: int | None) -> str:
    """PRD 11.2.1: night 0-5, morning 6-10, midday 11-14, afternoon 15-17, evening 18-23."""
    if hour is None:
        return "unknown"
    if hour <= 5:
        return "night"
    if hour <= 10:
        return "morning"
    if hour <= 14:
        return "midday"
    if hour <= 17:
        return "afternoon"
    return "evening"


def features_from_parts(
    *,
    description: str,
    merchant_key: str,
    amount: Decimal,
    payment_method: str,
    transaction_type: str,
    local_hour: int | None,
    weekday: int,
) -> dict[str, Any]:
    """Features from already-derived parts (what the ML service receives, PRD 14.2).

    ``local_hour`` is ``None`` when the transaction has no time; ``weekday`` is Monday = 0 in the
    user's timezone. ``online_features`` delegates here so both serving paths share one rule.
    """
    if amount <= 0:
        raise ValueError("amount must be > 0")
    return {
        "text": preprocess_description(description),
        "merchant_key": merchant_key,
        "log_amount": math.log1p(float(amount)),
        "payment_method": payment_method,
        "transaction_type": transaction_type,
        "hour_bucket": hour_bucket(local_hour),
        "is_weekend": int(weekday >= 5),
    }


def online_features(tx: TransactionInput) -> dict[str, Any]:
    """Features for one transaction (serving path)."""
    _, merchant_key = resolve_merchant(tx.merchant, tx.description)
    return features_from_parts(
        description=tx.description,
        merchant_key=merchant_key,
        amount=tx.amount,
        payment_method=tx.payment_method,
        transaction_type=tx.transaction_type,
        local_hour=tx.occurred.hour if tx.has_time else None,
        weekday=tx.occurred.weekday(),
    )


def parse_local_datetime(value: str) -> tuple[datetime, bool]:
    """Parse ``YYYY-MM-DD`` or ``YYYY-MM-DD HH:MM`` (dataset format) into (datetime, has_time)."""
    if len(value) <= 10:
        return datetime.fromisoformat(value), False
    return datetime.fromisoformat(value), True


def row_to_input(row: Any) -> TransactionInput:
    """Build a ``TransactionInput`` from a dataset row (used by tests and parity checks)."""
    occurred, has_time = parse_local_datetime(str(row["date"]))
    merchant = row["merchant"]
    return TransactionInput(
        description=str(row["description"]),
        merchant=None if pd.isna(merchant) else str(merchant),
        amount=Decimal(str(row["amount"])),
        transaction_type=str(row["type"]),
        payment_method=str(row["payment_method"]),
        occurred=occurred,
        has_time=has_time,
    )


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Features for many transactions (training path). Row order and index are preserved."""
    missing = set(INPUT_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"missing input columns: {sorted(missing)}")
    if (df["amount"].astype("float64") <= 0).any():
        raise ValueError("amount must be > 0")

    dates = df["date"].astype(str)
    has_time = dates.str.len() > 10
    stamp = pd.to_datetime(dates, format="ISO8601")
    hours = stamp.dt.hour.where(has_time)

    keys = [
        resolve_merchant(None if pd.isna(m) else str(m), str(d))[1]
        for m, d in zip(df["merchant"], df["description"], strict=True)
    ]
    out = pd.DataFrame(index=df.index)
    out["text"] = df["description"].astype(str).map(preprocess_description)
    out["merchant_key"] = keys
    out["log_amount"] = np.log1p(df["amount"].astype("float64"))
    out["payment_method"] = df["payment_method"].astype(str)
    out["transaction_type"] = df["type"].astype(str)
    out["hour_bucket"] = [hour_bucket(None if pd.isna(h) else int(h)) for h in hours]
    out["is_weekend"] = (stamp.dt.day_of_week >= 5).astype("int64")
    return out[list(FEATURE_COLUMNS)]


__all__ = [
    "features_from_parts",
    "FEATURE_COLUMNS",
    "HOUR_BUCKETS",
    "TransactionInput",
    "build_feature_frame",
    "hour_bucket",
    "online_features",
    "parse_local_datetime",
    "row_to_input",
]
