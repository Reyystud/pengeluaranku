"""Per-user behavior features of PRD 11.2.4, from the user's last complete periods.

``raw_features`` is the single code path: the backend job and the training script both call it,
so batch and online features cannot differ (PRD 11.1 parity). The caller passes only the rows that
fall inside the user's window (the last ``periods`` complete budget periods) and the window's
length in days; this module does no period arithmetic and never looks at other rows.

Raw features are interpretable (shares, ratios); ``model_matrix`` turns them into the space the
clusterer works in: log1p of the two money amounts and the centred log-ratio of the category
shares (compositional data, FR-13.02).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.clustering.config import ClusteringConfig
from ml.taxonomy import CATEGORIES

EXPENSE_CATEGORIES = tuple(c.slug for c in CATEGORIES if c.transaction_type == "expense")
SHARE_COLUMNS = tuple(f"category_share_{c}" for c in EXPENSE_CATEGORIES)
RAW_COLUMNS = (
    "avg_tx_amount",
    "monthly_expense",
    "tx_per_day",
    *SHARE_COLUMNS,
    "weekend_spend_ratio",
    "recurring_ratio",
    "small_tx_ratio",
    "income_regularity",
    "savings_rate",
)
MODEL_COLUMNS = (
    "log_avg_tx_amount",
    "log_monthly_expense",
    "tx_per_day",
    *(f"clr_{c}" for c in EXPENSE_CATEGORIES),
    "weekend_spend_ratio",
    "recurring_ratio",
    "small_tx_ratio",
    "income_regularity",
    "savings_rate",
)


def raw_features(
    rows: pd.DataFrame, days: int, n_periods: int, cfg: ClusteringConfig
) -> dict[str, float] | None:
    """Features of ONE user, or None when the window holds no expense.

    ``rows`` needs ``occurred_at`` (local time), ``type``, ``amount_f``, ``category`` and
    ``recurring`` (bool: linked to a recurring series). ``income_regularity`` and
    ``savings_rate`` are NaN when there is too little income to measure them.
    """
    expense = rows[rows["type"] == "expense"]
    if expense.empty or days <= 0 or n_periods <= 0:
        return None
    amount = expense["amount_f"].to_numpy(dtype=float)
    total = float(amount.sum())
    by_cat = expense.groupby("category")["amount_f"].sum()
    out: dict[str, float] = {
        "avg_tx_amount": float(amount.mean()),
        "monthly_expense": total / n_periods,
        "tx_per_day": len(expense) / days,
    }
    for slug in EXPENSE_CATEGORIES:
        out[f"category_share_{slug}"] = float(by_cat.get(slug, 0.0)) / total
    weekend = expense["occurred_at"].dt.dayofweek >= 5
    out["weekend_spend_ratio"] = float(amount[weekend.to_numpy()].sum()) / total
    recurring = expense["recurring"].to_numpy(dtype=bool)
    out["recurring_ratio"] = float(amount[recurring].sum()) / total
    out["small_tx_ratio"] = float((amount < cfg.small_tx_amount).mean())
    income = rows[rows["type"] == "income"]
    days_of_income = np.sort(income["occurred_at"].dt.normalize().unique())
    gaps = np.diff(days_of_income).astype("timedelta64[D]").astype(float)
    out["income_regularity"] = (
        float(gaps.std() / gaps.mean()) if len(gaps) >= 2 and gaps.mean() > 0 else float("nan")
    )
    earned = float(income["amount_f"].sum())
    out["savings_rate"] = (
        float(np.clip((earned - total) / earned, -1.0, 1.0)) if earned > 0 else float("nan")
    )
    return out


def model_matrix(raw: pd.DataFrame, cfg: ClusteringConfig) -> pd.DataFrame:
    """``raw`` (columns ``RAW_COLUMNS``) in the clusterer's space; NaN stay NaN (imputed later)."""
    out = pd.DataFrame(index=raw.index)
    out["log_avg_tx_amount"] = np.log1p(raw["avg_tx_amount"])
    out["log_monthly_expense"] = np.log1p(raw["monthly_expense"])
    out["tx_per_day"] = raw["tx_per_day"]
    shares = raw[list(SHARE_COLUMNS)].to_numpy(dtype=float) + cfg.clr_epsilon
    logs = np.log(shares)
    clr = logs - logs.mean(axis=1, keepdims=True)
    for j, slug in enumerate(EXPENSE_CATEGORIES):
        out[f"clr_{slug}"] = clr[:, j]
    for col in (
        "weekend_spend_ratio",
        "recurring_ratio",
        "small_tx_ratio",
        "income_regularity",
        "savings_rate",
    ):
        out[col] = raw[col]
    return out[list(MODEL_COLUMNS)]
