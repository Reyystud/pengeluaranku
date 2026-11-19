"""Locked evaluation splits (PRD section 10.4).

Leakage is the largest evaluation risk, so splits are a pure function of the dataset and
``SplitParams``: no randomness from numpy, only SHA-256 ordering, so results do not depend on
library versions or row order. Once the splits for a dataset version are committed under
``data_splits/<dataset_version>/`` they MUST NOT change without an ADR.

Definitions
-----------
* **Chronological order** of a user's rows: local timestamp ascending (date-only rows count as
  12:00, PRD 4.2), ties broken by ``transaction_id``.
* **Classifier**: ``held-out merchants`` (``merchant_holdout_pct`` of each category's merchants,
  at least one, never all) send *all* their rows to ``test_unseen_merchant``. The remaining rows
  of each user are cut chronologically into train / validation / test (70 / 15 / 15 by default).
* **Anomaly**: the same chronological cut over *all* of a user's rows (no merchant hold-out).
  Labels are used for evaluation only.
* **Forecast**: for each user, the last ``forecast_periods`` *complete* budget periods inside the
  data window; origins are day ``k`` (k in ``origin_days``, day 1 = period start) of each period.
  A forecast made at origin ``(period, k)`` may use only transactions dated on or before that
  day (``days_elapsed = k``, inclusive of today, PRD 4.5) and nothing later.
* **Clustering**: users split 50/50, stratified by archetype.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

SPLIT_VERSION = "splits-1"

CLASSIFIER_SPLITS = ("train", "validation", "test", "test_unseen_merchant")
ANOMALY_SPLITS = ("train", "validation", "test")


@dataclass(frozen=True)
class SplitParams:
    seed: int = 42
    train_pct: int = 70
    validation_pct: int = 15  # test gets the rest (15)
    merchant_holdout_pct: int = 15
    forecast_periods: int = 4
    origin_days: tuple[int, ...] = (5, 10, 15, 20)


@dataclass
class SplitResult:
    params: SplitParams
    assignments: pd.DataFrame  # transaction_id, user_id, classifier_split, anomaly_split
    user_cuts: pd.DataFrame
    heldout_merchants: pd.DataFrame  # merchant, category
    cluster_users: pd.DataFrame  # user_id, archetype, half
    forecast_periods: pd.DataFrame  # user_id, period_start, period_end

    def hashes(self) -> dict[str, str]:
        parts = {
            "assignments": hash_frame(self.assignments[_ASSIGNMENT_COLUMNS]),
            "heldout_merchants": hash_frame(self.heldout_merchants),
            "cluster_users": hash_frame(self.cluster_users),
            "forecast_periods": hash_frame(self.forecast_periods),
        }
        canonical = json.dumps(
            {"version": SPLIT_VERSION, "params": asdict(self.params), "parts": parts},
            sort_keys=True,
        )
        return {**parts, "split_hash": hashlib.sha256(canonical.encode()).hexdigest()}

    def counts(self) -> dict[str, Any]:
        return {
            "transactions": len(self.assignments),
            "users": len(self.cluster_users),
            "classifier": {
                k: int(v) for k, v in self.assignments["classifier_split"].value_counts().items()
            },
            "anomaly": {
                k: int(v) for k, v in self.assignments["anomaly_split"].value_counts().items()
            },
            "heldout_merchants": len(self.heldout_merchants),
            "forecast_periods": len(self.forecast_periods),
        }


_ASSIGNMENT_COLUMNS = ["transaction_id", "classifier_split", "anomaly_split"]


def hash_frame(df: pd.DataFrame) -> str:
    """SHA-256 of the frame's canonical CSV (row order as given; callers sort first)."""
    payload = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _digest(seed: int, kind: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{kind}:{value}".encode()).hexdigest()


def _sort_key(dates: pd.Series[str]) -> pd.Series[str]:
    return dates.where(dates.str.len() == 16, dates + " 12:00")


def _temporal_cut(
    ordered: pd.DataFrame, params: SplitParams, labels: tuple[str, str, str]
) -> tuple[pd.Series[str], pd.DataFrame]:
    """Label rows (already in chronological order per user) and return per-user cut points."""
    grouped = ordered.groupby("user_id", sort=False)
    n = grouped["user_id"].transform("size")
    position = grouped.cumcount()
    cut1 = n * params.train_pct // 100
    cut2 = n * (params.train_pct + params.validation_pct) // 100
    label = pd.Series(labels[2], index=ordered.index)
    label[position < cut2] = labels[1]
    label[position < cut1] = labels[0]
    cuts = (
        pd.DataFrame({"user_id": ordered["user_id"], "n": n, "cut1": cut1, "cut2": cut2})
        .drop_duplicates("user_id")
        .reset_index(drop=True)
    )
    return label, cuts


def _heldout_merchants(transactions: pd.DataFrame, params: SplitParams) -> pd.DataFrame:
    counts = transactions.groupby(["true_merchant", "true_category"]).size().reset_index(name="n")
    counts = counts.sort_values(
        ["true_merchant", "n", "true_category"], ascending=[True, False, True]
    )
    home = counts.drop_duplicates("true_merchant")[["true_merchant", "true_category"]]
    rows: list[tuple[str, str]] = []
    for category, group in home.groupby("true_category", sort=True):
        names = sorted(group["true_merchant"], key=lambda m: _digest(params.seed, "merchant", m))
        n = len(names)
        if n < 2:
            continue
        k = 0
        if params.merchant_holdout_pct > 0:
            k = min(n - 1, max(1, (params.merchant_holdout_pct * n + 50) // 100))
        if k == 0:
            continue
        rows.extend((name, str(category)) for name in names[:k])
    frame = pd.DataFrame(rows, columns=["merchant", "category"])
    return frame.sort_values("merchant").reset_index(drop=True)


def _cluster_users(users: pd.DataFrame, params: SplitParams) -> pd.DataFrame:
    parts = []
    for archetype, group in users.groupby("archetype", sort=True):
        ids = sorted(group["user_id"], key=lambda u: _digest(params.seed, "cluster", u))
        half = (len(ids) + 1) // 2
        parts.append(
            pd.DataFrame(
                {
                    "user_id": ids,
                    "archetype": archetype,
                    "half": ["A"] * half + ["B"] * (len(ids) - half),
                }
            )
        )
    return pd.concat(parts, ignore_index=True).sort_values("user_id").reset_index(drop=True)


def _period_start(year: int, month: int, start_day: int) -> date:
    return date(year, month, start_day)


def complete_periods(
    start_day: int, window_start: date, window_end_exclusive: date, last_n: int
) -> list[tuple[date, date]]:
    """The last ``last_n`` budget periods fully inside the data window (oldest first)."""
    last_day = window_end_exclusive - timedelta(days=1)
    periods: list[tuple[date, date]] = []
    year, month = window_start.year, window_start.month
    while True:
        start = _period_start(year, month, start_day)
        next_year, next_month = (year + month // 12, month % 12 + 1)
        next_start = _period_start(next_year, next_month, start_day)
        end = next_start - timedelta(days=1)
        if end > last_day:
            break
        if start >= window_start:
            periods.append((start, end))
        year, month = next_year, next_month
    return periods[-last_n:]


def _forecast_periods(
    users: pd.DataFrame, window_start: date, window_end_exclusive: date, params: SplitParams
) -> pd.DataFrame:
    by_start_day: dict[int, list[tuple[date, date]]] = {
        int(sd): complete_periods(
            int(sd), window_start, window_end_exclusive, params.forecast_periods
        )
        for sd in sorted(users["budget_period_start_day"].unique())
    }
    rows = [
        (u, start.isoformat(), end.isoformat())
        for u, sd in zip(users["user_id"], users["budget_period_start_day"], strict=True)
        for start, end in by_start_day[int(sd)]
    ]
    frame = pd.DataFrame(rows, columns=["user_id", "period_start", "period_end"])
    return frame.sort_values(["user_id", "period_start"]).reset_index(drop=True)


def forecast_origins(periods: pd.DataFrame, params: SplitParams) -> pd.DataFrame:
    """Expand periods into origins: day ``k`` of each period; data up to that day is usable."""
    rows = []
    for user_id, start, end in periods.itertuples(index=False):
        first = date.fromisoformat(start)
        for k in params.origin_days:
            rows.append((user_id, start, end, k, (first + timedelta(days=k - 1)).isoformat()))
    return pd.DataFrame(
        rows, columns=["user_id", "period_start", "period_end", "origin_day", "origin_date"]
    )


def compute_splits(
    transactions: pd.DataFrame,
    users: pd.DataFrame,
    window_start: date,
    window_end_exclusive: date,
    params: SplitParams | None = None,
) -> SplitResult:
    """Compute every split from the dataset. Pure and independent of input row order."""
    params = params or SplitParams()
    needed = {"transaction_id", "user_id", "date", "true_merchant", "true_category"}
    missing = needed - set(transactions.columns)
    if missing:
        raise ValueError(f"transactions missing columns: {sorted(missing)}")

    tx = transactions[sorted(needed)].copy()
    tx["_key"] = _sort_key(tx["date"])
    # Canonical order independent of how the file was stored: user, timestamp, transaction_id.
    tx = tx.sort_values(["user_id", "_key", "transaction_id"], kind="stable", ignore_index=True)

    anomaly_label, anomaly_cuts = _temporal_cut(tx, params, ANOMALY_SPLITS[:3])
    heldout = _heldout_merchants(tx, params)
    is_heldout = tx["true_merchant"].isin(set(heldout["merchant"]))

    classifier_label = pd.Series("test_unseen_merchant", index=tx.index)
    rest = tx[~is_heldout]
    rest_label, classifier_cuts = _temporal_cut(rest, params, ("train", "validation", "test"))
    classifier_label.loc[rest.index] = rest_label

    assignments = pd.DataFrame(
        {
            "transaction_id": tx["transaction_id"],
            "user_id": tx["user_id"],
            "classifier_split": classifier_label,
            "anomaly_split": anomaly_label,
        }
    ).sort_values("transaction_id", ignore_index=True)

    cuts = anomaly_cuts.rename(
        columns={"n": "anomaly_n", "cut1": "anomaly_cut1", "cut2": "anomaly_cut2"}
    )
    cuts = cuts.merge(
        classifier_cuts.rename(
            columns={"n": "classifier_n", "cut1": "classifier_cut1", "cut2": "classifier_cut2"}
        ),
        on="user_id",
        how="left",
    ).fillna(0)
    cut_columns = [c for c in cuts.columns if c != "user_id"]
    cuts[cut_columns] = cuts[cut_columns].astype("int64")
    cuts = cuts.sort_values("user_id", ignore_index=True)

    return SplitResult(
        params=params,
        assignments=assignments,
        user_cuts=cuts,
        heldout_merchants=heldout,
        cluster_users=_cluster_users(users, params),
        forecast_periods=_forecast_periods(users, window_start, window_end_exclusive, params),
    )


def assert_no_leakage(result: SplitResult, transactions: pd.DataFrame) -> None:
    """Sanity checks used by tests and by ``write_split_files``; raises ``AssertionError``."""
    tx = transactions[["transaction_id", "date", "true_merchant"]].merge(
        result.assignments, on="transaction_id", validate="one_to_one"
    )
    tx["_key"] = _sort_key(tx["date"])
    heldout = set(result.heldout_merchants["merchant"])
    unseen = tx["classifier_split"] == "test_unseen_merchant"
    assert unseen.equals(tx["true_merchant"].isin(heldout)), "held-out merchants leak"
    for column in ("classifier_split", "anomaly_split"):
        known = tx[tx[column].isin(("train", "validation", "test"))]
        grouped = known.groupby(["user_id", column])["_key"]
        first, last = grouped.min().unstack(), grouped.max().unstack()
        for earlier, later in (("train", "validation"), ("validation", "test"), ("train", "test")):
            overlapping = last[earlier].notna() & first[later].notna()
            violated = overlapping & (last[earlier] > first[later])
            assert not violated.any(), f"{column}: {earlier} overlaps {later}"


# ---- persistence -------------------------------------------------------------------------

_COMMITTED_FILES = {
    "heldout_merchants.csv": "heldout_merchants",
    "cluster_users.csv": "cluster_users",
    "forecast_periods.csv": "forecast_periods",
    "user_cuts.csv": "user_cuts",
}


def write_split_files(
    result: SplitResult,
    out_dir: Path,
    dataset_info: dict[str, Any],
    assignments_dir: Path | None = None,
) -> dict[str, Any]:
    """Write the small committed files + ``splits.json``; optionally the full ID lists."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, attribute in _COMMITTED_FILES.items():
        getattr(result, attribute).to_csv(out_dir / name, index=False, lineterminator="\n")
    summary = {
        "split_version": SPLIT_VERSION,
        "params": asdict(result.params),
        "dataset": dataset_info,
        "counts": result.counts(),
        "hashes": result.hashes(),
    }
    (out_dir / "splits.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if assignments_dir is not None:
        assignments_dir.mkdir(parents=True, exist_ok=True)
        result.assignments.to_parquet(assignments_dir / "assignments.parquet", index=False)
    return summary


def verify_split_files(result: SplitResult, committed_dir: Path) -> list[str]:
    """Compare freshly computed splits with the committed ``splits.json``; return mismatches."""
    committed = json.loads((committed_dir / "splits.json").read_text(encoding="utf-8"))
    fresh = result.hashes()
    problems = [
        f"{key}: committed {committed['hashes'].get(key)} != computed {value}"
        for key, value in fresh.items()
        if committed["hashes"].get(key) != value
    ]
    if committed["params"] != json.loads(json.dumps(asdict(result.params))):
        problems.append("params differ from committed splits.json")
    return problems
