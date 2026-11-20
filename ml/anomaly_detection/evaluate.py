"""Evaluate the baseline on the synthetic dataset (PRD 9.3), using the locked anomaly split.

    uv run python -m ml.anomaly_detection.evaluate --data data/synthetic/v1 \\
        --assignments data/splits/synthetic/v1/assignments.parquet --users 200 --out report.json

Rows of the ``validation`` and ``test`` anomaly splits are scored one by one with history strictly
before them (all earlier rows, including the training part). Generator labels are used only here,
to compute precision and recall; they never reach the detector. A deterministic user sample keeps
the run short (the full dataset has about 2 million rows); report the sample size with any number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ml.anomaly_detection.baseline import CategoryPrior, Transaction, detect
from ml.anomaly_detection.config import AnomalyConfig, load_anomaly_config, load_category_priors
from ml.anomaly_detection.history import build_history
from ml.evaluation.splits import _sort_key

PER_TX_TYPES = ("amount_spike", "frequency_burst", "new_merchant_high_value")


def sample_users(user_ids: list[str], n: int) -> list[str]:
    """First ``n`` users in SHA-256 order (the same selection rule as the splits: no RNG)."""
    ordered = sorted(
        user_ids, key=lambda u: hashlib.sha256(f"anomaly-eval:{u}".encode()).hexdigest()
    )
    return sorted(ordered[:n])


def score_user(
    rows: pd.DataFrame, cfg: AnomalyConfig, priors: dict[str, tuple[float, float]]
) -> pd.DataFrame:
    """One row per scored (validation/test) expense with the types the detector flagged."""
    rows = rows.sort_values(["occurred_at", "transaction_id"], kind="stable").reset_index(drop=True)
    rows["created_at"] = range(len(rows))
    out: list[dict[str, Any]] = []
    for _, row in rows[rows["anomaly_split"].isin(["validation", "test"])].iterrows():
        if row["type"] != "expense":
            continue
        prior = priors.get(str(row["category"]))
        history = build_history(
            rows,
            row["occurred_at"],
            str(row["category"]),
            str(row["merchant_key"]),
            cfg,
            CategoryPrior(*prior) if prior else None,
        )
        tx = Transaction(
            row["amount_dec"],
            str(row["category"]),
            str(row["merchant_key"]),
            str(row["merchant_key"]),
        )
        found = {d.anomaly_type: d for d in detect(tx, history, cfg)}
        out.append(
            {
                "transaction_id": row["transaction_id"],
                "split": row["anomaly_split"],
                "is_anomaly": bool(row["is_anomaly"]),
                "label_type": row["anomaly_type"] if isinstance(row["anomaly_type"], str) else None,
                "flagged": sorted(found),
                "severity": {k: v.severity for k, v in found.items()},
                "score": {k: v.score for k, v in found.items()},
            }
        )
    return pd.DataFrame(out)


def metrics(scored: pd.DataFrame) -> dict[str, Any]:
    """Row-level precision/recall per type, and overall (any flag vs. any labelled anomaly)."""
    result: dict[str, Any] = {}
    for kind in PER_TX_TYPES:
        flagged = scored["flagged"].apply(lambda f, k=kind: k in f)
        truth = scored["label_type"] == kind
        tp = int((flagged & truth).sum())
        result[kind] = {
            "tp": tp,
            "flagged": int(flagged.sum()),
            "labelled": int(truth.sum()),
            "precision": tp / int(flagged.sum()) if flagged.sum() else None,
            "recall": tp / int(truth.sum()) if truth.sum() else None,
        }
    flagged_any = scored["flagged"].apply(lambda f: any(k in PER_TX_TYPES for k in f))
    truth_any = scored["label_type"].isin(PER_TX_TYPES)
    tp = int((flagged_any & truth_any).sum())
    result["overall"] = {
        "tp": tp,
        "flagged": int(flagged_any.sum()),
        "labelled": int(truth_any.sum()),
        "precision": tp / int(flagged_any.sum()) if flagged_any.sum() else None,
        "recall": tp / int(truth_any.sum()) if truth_any.sum() else None,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    cfg = load_anomaly_config()
    priors = load_category_priors()
    tx = pd.read_parquet(args.data / "transactions.parquet")
    assign = pd.read_parquet(args.assignments, columns=["transaction_id", "anomaly_split"])
    users = sample_users(sorted(tx["user_id"].unique().tolist()), args.users)
    tx = tx[tx["user_id"].isin(users)].merge(assign, on="transaction_id")
    key = _sort_key(tx["date"].astype(str))
    tx["occurred_at"] = pd.to_datetime(key)
    tx["category"] = tx["true_category"]  # the label, as the app would hold after categorization
    tx["merchant_key"] = tx["true_merchant"].astype(str).str.lower()
    tx["amount_dec"] = tx["amount"]
    tx["amount"] = tx["amount"].astype(float)
    parts = [score_user(g, cfg, priors) for _, g in tx.groupby("user_id")]
    scored = pd.concat(parts, ignore_index=True)
    per_split = {s: metrics(scored[scored["split"] == s]) for s in ("validation", "test")}
    report = {
        "detector_version": cfg.version,
        "feature_version": cfg.feature_version,
        "users_sampled": len(users),
        "scored_rows": len(scored),
        "per_split": per_split,
        "overall": metrics(scored),
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
