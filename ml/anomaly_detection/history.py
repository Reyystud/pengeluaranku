"""Batch (DataFrame) version of the history features of 11.2.2, for evaluation and parity tests.

The backend computes the same fields in SQL (``app.repositories.anomalies``); a parity test pins
them together. Only rows strictly before ``as_of`` are used (``history_before``, PRD 11.1 rule 2).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from ml.anomaly_detection.baseline import CategoryPrior, UserHistory, p95
from ml.anomaly_detection.config import AnomalyConfig
from ml.features.point_in_time import history_before

DAY = timedelta(days=1)


def build_history(
    history: pd.DataFrame,
    as_of: datetime,
    category: str,
    merchant_key: str,
    cfg: AnomalyConfig,
    prior: CategoryPrior | None = None,
) -> UserHistory:
    """``history``: one user's rows (occurred_at, created_at, type, amount, category, key)."""
    seen = history_before(history, as_of)
    expenses = seen[seen["type"] == "expense"]
    in_cat = expenses[expenses["category"] == category]
    window = cfg.history_days * DAY
    cat_recent = in_cat[in_cat["occurred_at"] >= as_of - window]
    at_merchant = seen[seen["merchant_key"] == merchant_key] if merchant_key else seen.iloc[0:0]
    merchant_recent = at_merchant[
        (at_merchant["type"] == "expense") & (at_merchant["occurred_at"] >= as_of - window)
    ]
    recent_expenses = expenses[expenses["occurred_at"] >= as_of - window]
    first = seen["occurred_at"].min() if len(seen) else None
    return UserHistory(
        category_amounts=tuple(float(v) for v in cat_recent["amount"]),
        merchant_amounts=tuple(float(v) for v in merchant_recent["amount"]),
        merchant_seen=bool(len(at_merchant)),
        expense_p95=p95([float(v) for v in recent_expenses["amount"]]),
        expense_count=len(expenses),
        category_count_24h=int((in_cat["occurred_at"] > as_of - DAY).sum()),
        category_count_rate_window=int(
            (in_cat["occurred_at"] >= as_of - cfg.burst_rate_days * DAY).sum()
        ),
        history_days=0.0 if first is None else (as_of - first) / DAY,
        prior=prior,
    )
