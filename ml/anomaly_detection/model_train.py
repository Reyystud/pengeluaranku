"""Isolation Forest and LOF vs the baseline for ``amount_spike`` (PRD 7.6.3, 9.3, 16.3).

    uv run python -m ml.anomaly_detection.model_train [--users N] [--no-mlflow] [--out report.json]

Unsupervised models are fitted on the ``train`` anomaly split of a deterministic user sample, using
user-relative features (11.2.2). Labels are used only to score. The flag threshold of each model is
chosen on ``validation`` (max precision subject to recall >= target) and applied unchanged to
``test``. The baseline gets the same treatment: its ranking is the modified z-score gated by the
rule's amount conditions, so the two are compared at the same procedure. Rows labelled
``category_surge`` are left out: that anomaly is a weekly pattern found by a rule, not a
per-transaction score. Rows labelled with another per-transaction type are neither positives nor
negatives of the ``amount_spike`` comparison (they are real anomalies; flagging them is not an
error) but they are positives of the ``any anomaly`` view.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

from ml.anomaly_detection.config import load_anomaly_config, load_category_priors
from ml.anomaly_detection.model_features import FEATURE_VERSION, FEATURES, user_features
from ml.config import _load_yaml
from ml.evaluation.loading import load_transactions, sample_users

ROOT = Path(__file__).resolve().parents[2]
PER_TX = ("amount_spike", "frequency_burst", "new_merchant_high_value")


def build_frame(cfg_train: dict[str, Any]) -> pd.DataFrame:
    """Features + split + labels for every expense row of the sampled users."""
    cfg = load_anomaly_config()
    priors = load_category_priors()
    data_dir = ROOT / cfg_train["dataset"]["data_dir"]
    ids = pd.read_parquet(data_dir / "users.parquet")
    id_col = "user_id" if "user_id" in ids.columns else ids.columns[0]
    users = sample_users(
        sorted(ids[id_col].astype(str).tolist()),
        int(cfg_train["sample"]["users"]),
        str(cfg_train["sample"]["salt"]),
    )
    tx = load_transactions(data_dir, users)
    assign = pd.read_parquet(
        ROOT / cfg_train["dataset"]["assignments"], columns=["transaction_id", "anomaly_split"]
    )
    tx = tx.merge(assign, on="transaction_id", how="left")
    parts = []
    for _, g in tx.groupby("user_id", sort=False):
        g = g.reset_index(drop=True)
        feats = user_features(g, cfg, priors, cfg.min_category_history)
        meta = g.loc[
            feats.index,
            [
                "user_id",
                "transaction_id",
                "occurred_at",
                "amount_f",
                "anomaly_split",
                "is_anomaly",
                "anomaly_type",
                "archetype",
            ],
        ]
        parts.append(pd.concat([meta, feats], axis=1))
    return pd.concat(parts, ignore_index=True)


def best_threshold(y: np.ndarray, score: np.ndarray, recall_target: float) -> float | None:
    """Threshold with max precision among those whose recall is >= target (None if none)."""
    if not (y == 1).any():
        return None
    precision, recall, thresholds = precision_recall_curve(y, score)
    ok = recall[:-1] >= recall_target
    if not ok.any():
        return None
    best = np.flatnonzero(ok)[np.argmax(precision[:-1][ok])]
    return float(thresholds[best])


def at_threshold(y: np.ndarray, score: np.ndarray, thr: float | None) -> dict[str, Any]:
    if thr is None:
        return {"threshold": None, "flagged": 0, "tp": 0, "precision": None, "recall": 0.0}
    flag = score >= thr
    tp = int((flag & (y == 1)).sum())
    return {
        "threshold": thr,
        "flagged": int(flag.sum()),
        "tp": tp,
        "precision": tp / int(flag.sum()) if flag.sum() else None,
        "recall": tp / int((y == 1).sum()) if (y == 1).any() else None,
    }


def evaluate(
    frame: pd.DataFrame, scores: dict[str, np.ndarray], recall_target: float
) -> dict[str, Any]:
    """Metrics per scorer for the two views, threshold chosen on validation, applied on test."""
    label = frame["anomaly_type"].fillna("")
    is_spike = (label == "amount_spike").to_numpy()
    other = label.isin(("frequency_burst", "new_merchant_high_value")).to_numpy()
    any_tx = label.isin(PER_TX).to_numpy()
    split = frame["anomaly_split"].to_numpy()
    limited = (frame["history_n_cat"] < MIN_CAT).to_numpy()
    days = (
        frame[frame["anomaly_split"].isin(["validation", "test"])]
        .groupby(["user_id", "anomaly_split"])["occurred_at"]
        .agg(lambda s: (s.max() - s.min()).days + 1)
    )
    months = {
        s: float(days.xs(s, level="anomaly_split").sum()) / 30.4375 for s in ("validation", "test")
    }
    result: dict[str, Any] = {}
    for name, score in scores.items():
        res: dict[str, Any] = {}
        views = [("amount_spike", is_spike, ~other)]
        if name != "baseline":  # the baseline ranking only covers the amount rule, not bursts
            views.append(("any_anomaly", any_tx, np.ones(len(frame), dtype=bool)))
        for view, positive, keep in views:
            sel = {s: (split == s) & keep for s in ("validation", "test")}
            yv, sv = positive[sel["validation"]].astype(int), score[sel["validation"]]
            yt, st = positive[sel["test"]].astype(int), score[sel["test"]]
            thr = best_threshold(yv, sv, recall_target)
            test = at_threshold(yt, st, thr)
            fp = test["flagged"] - test["tp"]
            lim = sel["test"] & limited
            res[view] = {
                "validation": at_threshold(yv, sv, thr)
                | {"pr_auc": float(average_precision_score(yv, sv)) if yv.any() else None},
                "test": test
                | {
                    "pr_auc": float(average_precision_score(yt, st)) if yt.any() else None,
                    "false_positives": fp,
                    "false_positives_per_user_month": fp / months["test"],
                    "positives": int(yt.sum()),
                    "rows": int(len(yt)),
                },
                "test_limited_history": at_threshold(positive[lim].astype(int), score[lim], thr)
                | {"positives": int(positive[lim].sum()), "rows": int(lim.sum())},
            }
        if res["amount_spike"]["test"]["threshold"] is not None:
            thr = res["amount_spike"]["test"]["threshold"]
            t = split == "test"
            res["recall_by_type_test"] = {
                kind: (
                    float((score[t & (label == kind).to_numpy()] >= thr).mean())
                    if (t & (label == kind).to_numpy()).any()
                    else None
                )
                for kind in PER_TX
            }
        result[name] = res
    return result


MIN_CAT = load_anomaly_config().min_category_history


def baseline_score(frame: pd.DataFrame) -> np.ndarray:
    """Modified z where the rule's amount gates pass (7.6.2), else -1 so it ranks last."""
    cfg = load_anomaly_config()
    passes = (frame["amount_f"] >= cfg.min_alert_amount) & (
        frame["amount_f"] >= cfg.min_ratio_to_typical * frame["base_typ"]
    )
    return np.where(passes, frame["z_cat"].to_numpy(), -1.0)


def gate(
    result: dict[str, Any], model: str, min_gain: float, recall_target: float
) -> dict[str, Any]:
    """PRD 7.6.3: the model must beat the baseline on test precision at recall >= target."""
    m = result[model]["amount_spike"]["test"]
    b = result["baseline"]["amount_spike"]["test"]
    if m["precision"] is None:
        return {
            "model": model,
            "beats_baseline": False,
            "reason": "no threshold reaches the recall target on validation",
        }
    recall_ok = (m["recall"] or 0.0) >= recall_target
    base_p = b["precision"] or 0.0
    gain = m["precision"] - base_p
    return {
        "model": model,
        "beats_baseline": bool(gain > min_gain and recall_ok),
        "precision_gain": gain,
        "model_test_recall_meets_target": recall_ok,
        "baseline_test_precision": b["precision"],
        "baseline_test_recall": b["recall"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=None)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--cache", type=Path, default=None, help="parquet cache of the feature frame"
    )
    args = parser.parse_args()
    cfg = _load_yaml("train/anomaly.yaml")
    if args.users:
        cfg["sample"]["users"] = args.users
    recall_target = float(cfg["selection"]["recall_target"])
    t0 = time.time()
    if args.cache and args.cache.exists():
        frame = pd.read_parquet(args.cache)
    else:
        frame = build_frame(cfg)
        if args.cache:
            frame.to_parquet(args.cache)
    frame = frame[frame["anomaly_type"].fillna("") != "category_surge"].reset_index(drop=True)
    feature_seconds = time.time() - t0
    seed = int(cfg["seed"])
    x = frame[list(FEATURES)].to_numpy(dtype=float)
    train = (frame["anomaly_split"] == "train").to_numpy()

    iso = IsolationForest(
        n_estimators=int(cfg["isolation_forest"]["n_estimators"]),
        max_samples=int(cfg["isolation_forest"]["max_samples"]),
        random_state=seed,
        n_jobs=-1,
    ).fit(x[train])
    raw_iso = -iso.score_samples(x)
    ecdf_iso = np.sort(raw_iso[train])
    iso_score = np.searchsorted(ecdf_iso, raw_iso, side="right") / len(ecdf_iso)

    scaler = StandardScaler().fit(x[train])
    rng = np.random.default_rng(seed)
    fit_idx = rng.choice(
        np.flatnonzero(train),
        size=min(int(cfg["lof"]["fit_rows"]), int(train.sum())),
        replace=False,
    )
    lof = LocalOutlierFactor(n_neighbors=int(cfg["lof"]["n_neighbors"]), novelty=True).fit(
        scaler.transform(x[fit_idx])
    )
    evaluated = ~train
    raw_lof = np.full(len(frame), np.nan)
    raw_lof[evaluated] = -lof.score_samples(scaler.transform(x[evaluated]))
    raw_lof_train = -lof.score_samples(scaler.transform(x[fit_idx]))
    ecdf_lof = np.sort(raw_lof_train)
    lof_score = np.where(
        evaluated,
        np.searchsorted(ecdf_lof, np.nan_to_num(raw_lof), side="right") / len(ecdf_lof),
        0.0,
    )

    scores = {"baseline": baseline_score(frame), "isolation_forest": iso_score, "lof": lof_score}
    result = evaluate(frame, scores, recall_target)
    min_gain = float(cfg["selection"]["min_precision_gain"])
    decisions = [gate(result, m, min_gain, recall_target) for m in ("isolation_forest", "lof")]
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    ).stdout.strip()
    report = {
        "config_version": cfg["version"],
        "feature_version": FEATURE_VERSION,
        "dataset_version": cfg["dataset"]["dataset_version"],
        "users_sampled": int(frame["user_id"].nunique()),
        "rows": {
            s: int((frame["anomaly_split"] == s).sum()) for s in ("train", "validation", "test")
        },
        "recall_target": recall_target,
        "git_commit": commit,
        "feature_seconds": round(feature_seconds, 1),
        "results": result,
        "gate": decisions,
    }
    if not args.no_mlflow:
        from ml.tracking import log_run

        flat = {}
        for name in scores:
            t = result[name]["amount_spike"]["test"]
            flat[f"{name}_test_precision"] = t["precision"]
            flat[f"{name}_test_recall"] = t["recall"]
            flat[f"{name}_test_pr_auc"] = t["pr_auc"]
            flat[f"{name}_fp_per_user_month"] = t["false_positives_per_user_month"]
        report["mlflow_run_id"] = log_run(
            "anomaly-detector",
            f"{cfg['version']}-{commit}",
            {k: cfg[k] for k in ("version", "seed")}
            | {
                "users": report["users_sampled"],
                "dataset_version": cfg["dataset"]["dataset_version"],
                "feature_version": FEATURE_VERSION,
                "git_commit": commit,
            },
            flat,
            {"evaluation/report.json": report},
        )
    text = json.dumps(report, indent=2, default=float)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
