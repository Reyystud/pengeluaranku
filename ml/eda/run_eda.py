"""EDA on the TRAIN split of synthetic/v1 (PRD 20.3 T-04). Writes docs/figures/*.png + stats JSON.

Only classifier-train rows are used, so nothing here peeks at validation/test data.
Usage: uv run python -m ml.eda.run_eda
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "v1"
ASSIGN = ROOT / "data" / "splits" / "synthetic" / "v1" / "assignments.parquet"
FIG = ROOT / "docs" / "figures"
OUT = ROOT / "data" / "eda_stats.json"


def load() -> pd.DataFrame:
    tx = pd.read_parquet(DATA / "transactions.parquet")
    split = pd.read_parquet(ASSIGN, columns=["transaction_id", "classifier_split"])
    tx = tx.merge(split, on="transaction_id", validate="one_to_one")
    tx = tx[tx["classifier_split"] == "train"].copy()
    tx["amount"] = tx["amount"].astype("float64")  # EDA only; money stays Decimal elsewhere
    return tx


def main() -> None:
    tx = load()
    stats: dict[str, Any] = {"train_rows": len(tx)}
    exp = tx[tx["type"] == "expense"]

    # class balance (all types, label = true_category)
    bal = tx["true_category"].value_counts()
    stats["class_balance"] = {k: int(v) for k, v in bal.items()}
    stats["imbalance_ratio_max_min"] = float(bal.max() / bal.min())
    fig, ax = plt.subplots(figsize=(8, 5))
    bal.sort_values().plot.barh(ax=ax)
    ax.set_xlabel("rows (classifier train split)")
    ax.set_title("Class balance")
    fig.tight_layout()
    fig.savefig(FIG / "class_balance.png", dpi=110)
    plt.close(fig)

    # text length
    desc = tx["description"].fillna("")
    stats["desc_len"] = {
        k: float(v) for k, v in desc.str.len().describe(percentiles=[0.5, 0.95, 0.99]).items()
    }
    stats["desc_tokens_median"] = float(desc.map(lambda t: len(t.split())).median())
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(desc.str.len().clip(upper=100), bins=50)
    ax.set_xlabel("description length (chars, clipped at 100)")
    ax.set_title("Description length")
    fig.tight_layout()
    fig.savefig(FIG / "text_length.png", dpi=110)
    plt.close(fig)

    # amounts by archetype (expenses)
    by_arch = exp.groupby("archetype")["amount"].describe(percentiles=[0.5, 0.95]).round(0)
    stats["expense_amount_by_archetype"] = by_arch.to_dict(orient="index")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    data = [np.log10(g["amount"].to_numpy()) for _, g in exp.groupby("archetype")]
    ax.boxplot(data, tick_labels=[str(a) for a, _ in exp.groupby("archetype")], showfliers=False)
    ax.set_ylabel("log10(amount, Rp)")
    ax.set_title("Expense amount by archetype")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(FIG / "amount_by_archetype.png", dpi=110)
    plt.close(fig)

    # amount by category (median) and zero-ambiguity check: amount overlap between categories
    stats["expense_median_by_category"] = (
        exp.groupby("true_category")["amount"].median().round(0).to_dict()
    )

    # missingness / noise
    stats["merchant_null_share"] = float(tx["merchant"].isna().mean())
    stats["date_only_share"] = float((tx["date"].str.len() == 10).mean())
    stats["type_share"] = tx["type"].value_counts(normalize=True).round(4).to_dict()
    stats["payment_method_share"] = (
        tx["payment_method"].value_counts(normalize=True).round(4).to_dict()
    )
    stats["anomaly_share_of_expenses"] = float(exp["is_anomaly"].mean())
    stats["recurring_share"] = float(tx["recurring_series_id"].notna().mean())

    # ambiguity: merchants that appear with more than one label
    mc = tx.groupby(["true_merchant", "true_category"]).size().reset_index(name="n")
    multi = mc.groupby("true_merchant").filter(lambda g: len(g) > 1)
    total = mc.groupby("true_merchant")["n"].transform("sum")
    mc["share"] = mc["n"] / total
    amb = mc[mc["true_merchant"].isin(multi["true_merchant"])].sort_values(
        ["true_merchant", "n"], ascending=[True, False]
    )
    stats["ambiguous_merchants"] = {
        m: {str(r.true_category): int(str(r.n)) for r in g.itertuples()}
        for m, g in amb.groupby("true_merchant")
    }
    row_share = float(
        tx.merge(multi[["true_merchant"]].drop_duplicates(), on="true_merchant").shape[0] / len(tx)
    )
    stats["rows_of_multilabel_merchants"] = row_share
    minority = mc.sort_values("n", ascending=False).drop_duplicates("true_merchant", keep="first")
    maj = tx.merge(
        minority[["true_merchant", "true_category"]].rename(columns={"true_category": "maj"}),
        on="true_merchant",
    )
    stats["minority_label_share"] = float((maj["true_category"] != maj["maj"]).mean())

    # samples of noisy descriptions (synthetic) for the doc
    stats["samples"] = (
        exp.sample(12, random_state=0)[["description", "amount", "true_category"]]
        .assign(amount=lambda d: d["amount"].round(0))
        .to_dict(orient="records")
    )

    # per-user volume
    per_user = tx.groupby("user_id").size()
    stats["tx_per_user_train"] = {
        k: float(v) for k, v in per_user.describe(percentiles=[0.05, 0.5, 0.95]).items()
    }
    stats["tx_per_user_by_archetype_median"] = (
        tx.groupby(["archetype", "user_id"]).size().groupby("archetype").median().to_dict()
    )

    OUT.write_text(json.dumps(stats, indent=2, default=float, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT} and figures in {FIG}")


if __name__ == "__main__":
    main()
