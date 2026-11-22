"""Fit and judge the behavior clusterer on the synthetic dataset (PRD 9.1, 9.5, FR-13.05).

    uv run python -m ml.clustering.train [--write-model] [--out report.json]

The ship rule (silhouette >= 0.40, ARI across 5 seeds >= 0.80, nameable segments) is in
``config/clustering.yaml``. Candidates: K-Means for k in 3..8 (k by silhouette), a Gaussian mixture
for the same k, DBSCAN on a small grid. Stability: ARI between 5 K-Means seeds, and between two
models fitted on the two halves of the users (``cluster_users.csv``) and applied to everyone.
ARI against the generator's archetypes is a sanity check only (FR-13.05).
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from sklearn.cluster import DBSCAN, KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.mixture import GaussianMixture

from ml.clustering.config import ClusteringConfig, load_clustering_config
from ml.clustering.features import RAW_COLUMNS, raw_features
from ml.clustering.model import Clusterer, fit, prepare
from ml.config import _load_yaml, config_dir

ROOT = Path(__file__).resolve().parents[2]
DBSCAN_GRID = tuple(itertools.product((2.0, 3.0, 4.0, 5.0), (10,)))  # (eps, min_samples)


def build_raw(cfg_all: dict[str, Any], cfg: ClusteringConfig) -> tuple[pd.DataFrame, pd.Series]:
    """Raw features of every user over their last ``cfg.periods`` complete periods + archetypes."""
    data_dir = ROOT / cfg_all["dataset"]["data_dir"]
    cols = [
        "user_id",
        "date",
        "type",
        "amount",
        "true_category",
        "recurring_series_id",
        "archetype",
    ]
    tx = pd.read_parquet(data_dir / "transactions.parquet", columns=cols)
    tx["occurred_at"] = pd.to_datetime(tx["date"].astype(str), format="mixed")
    tx["amount_f"] = tx["amount"].astype(float)
    tx["category"] = tx["true_category"]
    tx["recurring"] = tx["recurring_series_id"].notna()
    periods = pd.read_csv(
        ROOT / cfg_all["dataset"]["periods"], parse_dates=["period_start", "period_end"]
    )
    rows, arche = {}, tx.groupby("user_id")["archetype"].first()
    grouped = dict(tuple(tx.groupby("user_id")))
    for user, p in periods.sort_values("period_start").groupby("user_id"):
        win = p.tail(cfg.periods)
        if len(win) < cfg.min_periods or user not in grouped:
            continue
        start, end = win["period_start"].min(), win["period_end"].max() + pd.Timedelta(days=1)
        g = grouped[user]
        g = g[(g["occurred_at"] >= start) & (g["occurred_at"] < end)]
        feats = raw_features(g, int((end - start).days), len(win), cfg)
        if feats is not None:
            rows[user] = feats
    raw = pd.DataFrame.from_dict(rows, orient="index")[list(RAW_COLUMNS)]
    return raw, arche.reindex(raw.index)


def mean_pairwise_ari(labelings: list[np.ndarray]) -> tuple[float, float]:
    scores = [adjusted_rand_score(a, b) for a, b in itertools.combinations(labelings, 2)]
    return float(np.mean(scores)), float(np.min(scores))


def run(
    cfg_all: dict[str, Any], cfg: ClusteringConfig
) -> tuple[dict[str, Any], pd.DataFrame, Clusterer]:
    raw, archetype = build_raw(cfg_all, cfg)
    x, _, _, _ = prepare(raw, cfg)
    sel, rule = cfg_all["selection"], cfg_all["ship_rule"]
    ks = range(int(sel["k_min"]), int(sel["k_max"]) + 1)
    kmeans: dict[int, dict[str, float]] = {}
    gmm: dict[int, float] = {}
    for k in ks:
        labels = KMeans(k, n_init=int(sel["n_init"]), random_state=cfg.seed).fit_predict(x)
        kmeans[k] = {"silhouette": float(silhouette_score(x, labels))}
        g = GaussianMixture(k, covariance_type="diag", n_init=3, random_state=cfg.seed).fit_predict(
            x
        )
        gmm[k] = float(silhouette_score(x, g)) if len(set(g)) > 1 else float("nan")
    best_k = max(kmeans, key=lambda k: kmeans[k]["silhouette"])
    dbscan = []
    for eps, min_samples in DBSCAN_GRID:
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(x)
        core = labels >= 0
        clusters = len(set(labels[core]))
        dbscan.append(
            {
                "eps": eps,
                "min_samples": min_samples,
                "clusters": clusters,
                "noise_share": float(1 - core.mean()),
                "silhouette": float(silhouette_score(x[core], labels[core]))
                if clusters > 1
                else None,
            }
        )
    seeds = [
        KMeans(best_k, n_init=int(sel["n_init"]), random_state=cfg.seed + s).fit_predict(x)
        for s in range(int(sel["stability_seeds"]))
    ]
    ari_mean, ari_min = mean_pairwise_ari(seeds)
    halves = (
        pd.read_csv(ROOT / cfg_all["dataset"]["users"])
        .set_index("user_id")["half"]
        .reindex(raw.index)
    )
    models = {h: fit(raw[halves == h], best_k, cfg, "half") for h in ("A", "B")}
    labels_ab = [models[h].assign(raw, cfg)[0] for h in ("A", "B")]
    final = fit(raw, best_k, cfg, cfg_all["version"], int(sel["n_init"]))
    final_labels, _ = final.assign(raw, cfg)
    silhouette = kmeans[best_k]["silhouette"]
    report = {
        "config_version": cfg_all["version"],
        "dataset_version": cfg_all["dataset"]["dataset_version"],
        "users": len(raw),
        "k_selected": best_k,
        "kmeans": {str(k): v for k, v in kmeans.items()},
        "gmm_silhouette": {str(k): v for k, v in gmm.items()},
        "dbscan": dbscan,
        "silhouette": silhouette,
        "ari_seeds_mean": ari_mean,
        "ari_seeds_min": ari_min,
        "ari_split_halves": float(adjusted_rand_score(*labels_ab)),
        "ari_vs_archetype": float(adjusted_rand_score(archetype.astype(str), final_labels)),
        "segment_sizes": [s.size for s in final.segments],
        "ship_rule": {
            "silhouette_ok": bool(silhouette >= float(rule["min_silhouette"])),
            "ari_seeds_ok": bool(ari_mean >= float(rule["min_ari_seeds"])),
            "nameable": "manual: see the centroid table",
        },
        "git_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        ).stdout.strip(),
    }
    centroids = raw.assign(segment=final_labels).groupby("segment").mean().round(4)
    centroids["users"] = raw.assign(segment=final_labels).groupby("segment").size()
    crosstab = pd.crosstab(final_labels, archetype.to_numpy())
    report["archetype_crosstab"] = {
        str(i): {str(c): int(v) for c, v in row.items()} for i, row in crosstab.iterrows()
    }
    return report, centroids, final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--write-model", action="store_true", help="write config/clusterer_model.yaml"
    )
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args()
    cfg_all = _load_yaml("clustering.yaml")
    report, centroids, model = run(cfg_all, load_clustering_config())
    if args.write_model:
        path = config_dir() / "clusterer_model.yaml"
        keep: dict[str, Any] = {}
        if (
            path.exists()
        ):  # names written by a person survive a refit only for the same model version
            old = yaml.safe_load(path.read_text(encoding="utf-8"))
            if old.get("version") == model.version:
                keep = {s["id"]: s for s in old["segments"]}
        for s in model.segments:
            if s.id in keep:
                s.name, s.description = (
                    keep[s.id].get("name", ""),
                    keep[s.id].get("description", ""),
                )
        path.write_text(
            "# Behavior clusterer artifact (PRD 11.6, FR-13.03). Generated by\n"
            "# `python -m ml.clustering.train --write-model`; segment names and descriptions are\n"
            "# written by a person after inspecting the centroids. Contains no user data.\n"
            + yaml.safe_dump(model.to_dict(), sort_keys=False),
            encoding="utf-8",
        )
    if not args.no_mlflow:
        from ml.tracking import log_run

        flat = {
            "silhouette": report["silhouette"],
            "ari_seeds_mean": report["ari_seeds_mean"],
            "ari_split_halves": report["ari_split_halves"],
            "ari_vs_archetype": report["ari_vs_archetype"],
            "k": float(report["k_selected"]),
        }
        report["mlflow_run_id"] = log_run(
            "behavior-clusterer",
            f"{cfg_all['version']}-{report['git_commit']}",
            {
                "config_version": cfg_all["version"],
                "seed": cfg_all["seed"],
                "dataset_version": report["dataset_version"],
            },
            flat,
            {
                "evaluation/report.json": report,
                "evaluation/centroids.json": json.loads(centroids.to_json(orient="index")),
            },
        )
    text = json.dumps(report, indent=2, default=float)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    print(centroids.T.to_string())


if __name__ == "__main__":
    main()
