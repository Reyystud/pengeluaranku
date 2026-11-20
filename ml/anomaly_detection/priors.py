"""Compute the category-level cold-start priors (PRD 7.6.4) from a real dataset run.

    uv run python -m ml.anomaly_detection.priors --data data/synthetic/v1 \
        --splits data_splits/synthetic/v1 --assignments data/splits/synthetic/v1/assignments.parquet

Uses only rows of the anomaly ``train`` split that are not labelled anomalous (labels are for
evaluation, but the priors are a robust median/MAD, so injected rows would only widen them; they
are excluded so the prior describes normal spending). Writes ``config/anomaly_priors.yaml`` with
the dataset identity, so the numbers can be traced to a run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from ml.anomaly_detection.stats import mad, median
from ml.config import config_dir


def train_rows(data: Path, assignments: Path) -> pd.DataFrame:
    """Rows of the anomaly ``train`` split (``make splits`` writes ``assignments.parquet``)."""
    tx = pd.read_parquet(
        data / "transactions.parquet",
        columns=["transaction_id", "type", "amount", "true_category", "is_anomaly"],
    )
    train = pd.read_parquet(assignments, columns=["transaction_id", "anomaly_split"])
    ids = train.loc[train["anomaly_split"] == "train", "transaction_id"]
    return tx[tx["transaction_id"].isin(set(ids))]


def compute(rows: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    normal = rows[(rows["type"] == "expense") & (~rows["is_anomaly"].astype(bool))]
    for category, group in normal.groupby("true_category"):
        logs = np.log1p(group["amount"].astype(float).to_numpy()).tolist()
        if len(logs) < 2:
            continue
        out[str(category)] = {
            "median": round(median(logs), 6),
            "mad": round(mad(logs), 6),
            "n": len(logs),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--splits", type=Path, required=True, help="data_splits/<dataset> (committed)"
    )
    parser.add_argument(
        "--assignments", type=Path, required=True, help="data/splits/<dataset>/assignments.parquet"
    )
    parser.add_argument("--out", type=Path, default=config_dir() / "anomaly_priors.yaml")
    args = parser.parse_args()
    manifest = json.loads((args.data / "manifest.json").read_text(encoding="utf-8"))
    split_info = json.loads((args.splits / "splits.json").read_text(encoding="utf-8"))
    categories = compute(train_rows(args.data, args.assignments))
    document = {
        "source": {
            "dataset": f"{manifest['dataset_name']}",
            "seed": manifest["seed"],
            "generator_version": manifest["generator_version"],
            "split_hash": split_info["hashes"]["split_hash"],
            "split": "anomaly train, normal expense rows",
        },
        "categories": categories,
    }
    args.out.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    print(f"wrote {args.out} ({len(categories)} categories)")


if __name__ == "__main__":
    main()
