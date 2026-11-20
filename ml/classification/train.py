"""Train and evaluate the classifier candidates (PRD 9.1, 9.2, 9.6). ``make train-local``.

Usage: uv run python -m ml.classification.train [--models logreg linear_svm lightgbm]
Every metric written here comes from the run itself; nothing is hard-coded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from numpy.typing import NDArray  # noqa: E402

from ml.classification.calibration import IsotonicOvR  # noqa: E402
from ml.classification.config import load_train_config  # noqa: E402
from ml.classification.data import cap_per_class, load_split_frames  # noqa: E402
from ml.classification.metrics import (  # noqa: E402
    confident_errors,
    coverage_curve,
    expected_calibration_error,
    slice_metrics,
    summarize,
)
from ml.classification.pipeline import (  # noqa: E402
    batched_scores,
    build_transformer,
    has_probabilities,
    make_model,
    scores,
)
from ml.classification.thresholds import compute_report  # noqa: E402
from ml.features import FEATURE_VERSION  # noqa: E402
from ml.taxonomy import MODEL_LABELS, TAXONOMY_VERSION  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LABELS = list(MODEL_LABELS)
LABEL_ID = {name: i for i, name in enumerate(LABELS)}
MODEL_NAME = "transaction-classifier"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _encode(frame: pd.DataFrame) -> NDArray[np.int64]:
    return np.asarray(frame["label"].map(LABEL_ID).to_numpy(), dtype=np.int64)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _evaluate_split(
    name: str,
    frame: pd.DataFrame,
    y: NDArray[np.int64],
    raw: NDArray[np.float64],
    proba: NDArray[np.float64],
    probabilistic: bool,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    ev = cfg["evaluation"]
    bins = int(ev["ece_bins"])
    result = summarize(proba, y, LABELS, bins)
    result["ece_before_calibration"] = (
        expected_calibration_error(raw, y, bins) if probabilistic else None
    )
    result["coverage_curve"] = coverage_curve(proba, y, list(ev["coverage_thresholds"]))
    result["by_archetype"] = slice_metrics(proba, y, frame["archetype"], LABELS)
    result["confident_errors"] = confident_errors(
        proba, y, frame, LABELS, int(ev["error_analysis_top"])
    )
    result["split"] = name
    return result


def _latency_ms(
    transformer: Any, model: Any, calibrator: IsotonicOvR, frame: pd.DataFrame
) -> dict[str, float]:
    """Per-row transform + score + calibrate latency (excludes feature extraction and I/O)."""
    sample = frame.sample(min(300, len(frame)), random_state=0)
    times = []
    for i in range(len(sample)):
        row = sample.iloc[[i]]
        start = time.perf_counter()
        X = transformer.transform(row).tocsr()
        calibrator.predict_proba(scores(model, X))
        times.append((time.perf_counter() - start) * 1000.0)
    return {"p50_ms": float(np.percentile(times, 50)), "p95_ms": float(np.percentile(times, 95))}


def _train_one(
    name: str,
    cfg: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    train_cap: pd.DataFrame,
    main_transformer: Any,
    X_train: Any,
) -> dict[str, Any]:
    seed = int(cfg["seed"])
    started = time.perf_counter()
    if name == "lightgbm":
        sub = cap_per_class(
            frames["train"], int(cfg["models"]["lightgbm"]["max_rows_per_class"]), seed
        )
        transformer = build_transformer(cfg, int(cfg["lightgbm_tfidf_max_features"]))
        rng = np.random.default_rng(seed)
        is_eval = rng.random(len(sub)) < 0.1
        fit_frame, eval_frame = sub[~is_eval], sub[is_eval]
        X_fit = transformer.fit_transform(fit_frame).tocsr()
        X_eval = transformer.transform(eval_frame).tocsr()
        model = make_model(name, cfg, seed)
        import lightgbm as lgb

        model.fit(
            X_fit,
            _encode(fit_frame),
            eval_X=X_eval,
            eval_y=_encode(eval_frame),
            callbacks=[
                lgb.early_stopping(
                    int(cfg["models"]["lightgbm"]["early_stopping_rounds"]), verbose=False
                )
            ],
        )
        train_rows = len(fit_frame)
    else:
        transformer = main_transformer
        model = make_model(name, cfg, seed)
        model.fit(X_train, _encode(train_cap))
        train_rows = len(train_cap)
    fit_seconds = time.perf_counter() - started

    probabilistic = has_probabilities(model)
    val_raw = batched_scores(model, transformer, frames["validation"])
    y_val = _encode(frames["validation"])
    calibrator = IsotonicOvR().fit(val_raw, y_val)

    result: dict[str, Any] = {
        "model": name,
        "train_rows": int(train_rows),
        "fit_seconds": fit_seconds,
        "n_features": int(transformer.transform(frames["validation"].iloc[:5]).shape[1]),
        "probabilistic": probabilistic,
    }
    # Validation metrics use the calibrator fitted on the same rows: for model selection only.
    result["validation"] = _evaluate_split(
        "validation",
        frames["validation"],
        y_val,
        val_raw,
        calibrator.predict_proba(val_raw),
        probabilistic,
        cfg,
    )
    for split in ("test", "test_unseen_merchant"):
        raw = batched_scores(model, transformer, frames[split])
        result[split] = _evaluate_split(
            split,
            frames[split],
            _encode(frames[split]),
            raw,
            calibrator.predict_proba(raw),
            probabilistic,
            cfg,
        )
    result["latency"] = _latency_ms(transformer, model, calibrator, frames["test"])
    result["_artifacts"] = {"transformer": transformer, "model": model, "calibrator": calibrator}
    return result


def select_winner(results: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    """PRD 9.1 ship rule on VALIDATION macro F1 (the test split is not used for selection)."""
    rule = cfg["decision_rule"]
    base = rule["baseline"]
    margin = float(rule["min_macro_f1_gain_points"]) / 100.0
    base_f1 = results[base]["validation"]["macro_f1"]
    best_name, best_f1 = base, base_f1
    for name, res in results.items():
        f1 = res["validation"]["macro_f1"]
        if name != base and f1 >= base_f1 + margin and f1 > best_f1:
            best_name, best_f1 = name, f1
    return {
        "winner": best_name,
        "baseline": base,
        "baseline_validation_macro_f1": base_f1,
        "winner_validation_macro_f1": best_f1,
        "required_gain_points": float(rule["min_macro_f1_gain_points"]),
        "selected_on": "validation",
    }


def _plots(results: dict[str, dict[str, Any]], winner: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cm = np.array(results[winner]["test"]["confusion_matrix"], dtype=float)
    cm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1.0)
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.imshow(cm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(LABELS)), LABELS, rotation=90, fontsize=7)
    ax.set_yticks(range(len(LABELS)), LABELS, fontsize=7)
    ax.set_title(f"Confusion matrix (row-normalized), {winner}, test")
    fig.tight_layout()
    fig.savefig(out / "confusion_matrix.png", dpi=110)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for split, ax in zip(("test", "test_unseen_merchant"), axes, strict=True):
        for name, res in results.items():
            curve = res[split]["coverage_curve"]
            ax.plot(
                [c["coverage"] for c in curve],
                [c["precision"] for c in curve],
                marker="o",
                label=name,
            )
        ax.set_xlabel("coverage (share auto-applied)")
        ax.set_ylabel("precision of auto-applied")
        ax.set_title(split)
        ax.legend()
    fig.tight_layout()
    fig.savefig(out / "coverage_curve.png", dpi=110)
    plt.close(fig)


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"# Classifier evaluation ({report['run_id']})",
        "",
        f"Dataset {report['dataset']['version']} (split_hash `{report['dataset']['split_hash']}`), "
        f"feature version {report['feature_version']}, git `{report['git_commit']}`.",
        "",
        "| model | train rows | val macro F1 | test macro F1 | unseen macro F1 | test acc | "
        "test ECE before | test ECE after | P95 ms/row |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, res in report["models"].items():
        before = res["test"]["ece_before_calibration"]
        lines.append(
            f"| {name} | {res['train_rows']} | {res['validation']['macro_f1']:.4f} | "
            f"{res['test']['macro_f1']:.4f} | {res['test_unseen_merchant']['macro_f1']:.4f} | "
            f"{res['test']['accuracy']:.4f} | {'n/a' if before is None else f'{before:.4f}'} | "
            f"{res['test']['ece']:.4f} | {res['latency']['p95_ms']:.1f} |"
        )
    sel = report["selection"]
    lines += [
        "",
        f"Decision: **{sel['winner']}** (baseline {sel['baseline']}, selected on validation).",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _log_mlflow(
    report: dict[str, Any], results: dict[str, dict[str, Any]], model_dir: Path, cfg: dict[str, Any]
) -> None:
    import mlflow
    from mlflow.tracking import MlflowClient

    base = ROOT / "data" / "mlflow"
    base.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{base / 'mlflow.db'}")
    name = "classifier"
    exp = mlflow.get_experiment_by_name(name)
    exp_id = (
        exp.experiment_id
        if exp
        else mlflow.create_experiment(name, artifact_location=(base / "artifacts").as_uri())
    )
    winner = report["selection"]["winner"]
    for model_name, res in results.items():
        with mlflow.start_run(
            experiment_id=exp_id, run_name=f"{model_name}-{report['run_id']}"
        ) as run:
            mlflow.log_params(
                {
                    "model": model_name,
                    "seed": cfg["seed"],
                    "dataset_version": report["dataset"]["version"],
                    "split_hash": report["dataset"]["split_hash"],
                    "feature_version": report["feature_version"],
                    "taxonomy_version": TAXONOMY_VERSION,
                    "git_commit": report["git_commit"],
                    "train_rows": res["train_rows"],
                    "config_version": cfg["version"],
                }
            )
            mlflow.log_metrics(
                {
                    "val_macro_f1": res["validation"]["macro_f1"],
                    "test_macro_f1": res["test"]["macro_f1"],
                    "test_weighted_f1": res["test"]["weighted_f1"],
                    "test_accuracy": res["test"]["accuracy"],
                    "test_ece_after": res["test"]["ece"],
                    "unseen_macro_f1": res["test_unseen_merchant"]["macro_f1"],
                    "unseen_accuracy": res["test_unseen_merchant"]["accuracy"],
                    "fit_seconds": res["fit_seconds"],
                    "latency_p95_ms": res["latency"]["p95_ms"],
                }
            )
            mlflow.log_dict(
                {k: v for k, v in res.items() if not k.startswith("_")}, "evaluation/report.json"
            )
            if model_name == winner:
                mlflow.log_artifacts(str(model_dir), artifact_path="model")
                client = MlflowClient()
                try:
                    client.create_registered_model(MODEL_NAME)
                except mlflow.exceptions.MlflowException:
                    pass  # already exists
                version = client.create_model_version(
                    MODEL_NAME, source=f"runs:/{run.info.run_id}/model", run_id=run.info.run_id
                )
                client.set_registered_model_alias(MODEL_NAME, "candidate", version.version)
                report["mlflow"] = {"run_id": run.info.run_id, "version": str(version.version)}


def fit_candidates(
    cfg: dict[str, Any], frames: dict[str, pd.DataFrame], names: list[str]
) -> dict[str, dict[str, Any]]:
    """Fit and evaluate every candidate (PRD 16.1 step 5-7); shared by ``make train-local``/flow."""
    seed = int(cfg["seed"])
    train_cap = cap_per_class(frames["train"], int(cfg["sampling"]["max_rows_per_class"]), seed)
    print(f"train cap: {len(train_cap)} rows", flush=True)
    main_transformer = build_transformer(cfg)
    X_train = main_transformer.fit_transform(train_cap).tocsr()
    print(f"features: {X_train.shape}", flush=True)
    results: dict[str, dict[str, Any]] = {}
    for name in names:
        print(f"training {name} ...", flush=True)
        results[name] = _train_one(name, cfg, frames, train_cap, main_transformer, X_train)
        r = results[name]
        print(
            f"  {name}: val macro F1 {r['validation']['macro_f1']:.4f}, "
            f"test {r['test']['macro_f1']:.4f}, "
            f"unseen {r['test_unseen_merchant']['macro_f1']:.4f}, "
            f"fit {r['fit_seconds']:.0f}s",
            flush=True,
        )
    return results


def write_run_dir(
    cfg: dict[str, Any],
    frames: dict[str, pd.DataFrame],
    results: dict[str, dict[str, Any]],
    out: Path,
    git_commit: str | None = None,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    """Write model.joblib, evaluation files and metadata.json for the winner; return the report."""
    ds = cfg["dataset"]
    selection = select_winner(results, cfg)
    winner = selection["winner"]
    split_info = json.loads(
        (root / "data_splits" / ds["dataset_version"] / "splits.json").read_text()
    )
    manifest = json.loads((root / ds["data_dir"] / "manifest.json").read_text())
    run_id = time.strftime("%Y%m%d-%H%M%S")
    model_dir = out / run_id
    suffix = 1
    while model_dir.exists():  # two runs inside one second must not share a directory
        suffix += 1
        model_dir = out / f"{run_id}-{suffix}"
    model_dir.mkdir(parents=True)

    art = results[winner]["_artifacts"]
    joblib.dump(
        {**art, "labels": LABELS, "feature_version": FEATURE_VERSION}, model_dir / "model.joblib"
    )
    report: dict[str, Any] = {
        "run_id": model_dir.name,
        "git_commit": git_commit or _git("rev-parse", "--short", "HEAD"),
        "feature_version": FEATURE_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "dataset": {
            "version": ds["dataset_version"],
            "split_hash": split_info["hashes"]["split_hash"],
            "transactions_sha256": manifest["files_sha256"]["transactions.parquet"],
        },
        "config": cfg,
        "selection": selection,
        "models": {
            n: {k: v for k, v in r.items() if not k.startswith("_")} for n, r in results.items()
        },
    }
    evaluation = model_dir / "evaluation"
    evaluation.mkdir()
    (evaluation / "report.json").write_text(
        json.dumps(report, indent=2, default=float), encoding="utf-8"
    )
    _write_markdown(report, evaluation / "report.md")
    _plots(results, winner, evaluation / "plots")
    thresholds = compute_report(art, frames, cfg["thresholds"])
    (evaluation / "thresholds.json").write_text(
        json.dumps(thresholds, indent=2, default=float), encoding="utf-8"
    )
    metadata = {
        "model_name": MODEL_NAME,
        "model_type": winner,
        "feature_version": FEATURE_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": report["git_commit"],
        "dataset": {"name": "synthetic", **report["dataset"]},
        "decision_thresholds": thresholds["decision_thresholds"],
        "labels": LABELS,
        "artifact_sha256": {"model.joblib": _sha256(model_dir / "model.joblib")},
    }
    (model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return report, model_dir


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ml.classification.train")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--models", nargs="+", default=["logreg", "linear_svm", "lightgbm"])
    parser.add_argument("--max-rows-per-class", type=int, default=None)
    parser.add_argument("--out", type=Path, default=ROOT / "models" / MODEL_NAME)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument(
        "--relog", type=Path, default=None, help="log an existing run dir to MLflow"
    )
    args = parser.parse_args(argv)

    if args.relog is not None:
        saved = json.loads((args.relog / "evaluation" / "report.json").read_text())
        _log_mlflow(saved, saved["models"], args.relog, saved["config"])
        (args.relog / "evaluation" / "report.json").write_text(
            json.dumps(saved, indent=2, default=float), encoding="utf-8"
        )
        print(f"logged {args.relog} to MLflow: {saved.get('mlflow')}")
        return 0
    cfg = load_train_config(args.config)
    if args.max_rows_per_class is not None:
        cfg["sampling"]["max_rows_per_class"] = args.max_rows_per_class
    ds = cfg["dataset"]
    print("loading splits ...", flush=True)
    frames = load_split_frames(ROOT / ds["data_dir"], ROOT / ds["assignments"])
    for split, frame in frames.items():
        print(f"  {split}: {len(frame)} rows", flush=True)
    results = fit_candidates(cfg, frames, args.models)
    report, model_dir = write_run_dir(cfg, frames, results, args.out)
    evaluation = model_dir / "evaluation"
    winner = report["selection"]["winner"]
    if not args.no_mlflow:
        _log_mlflow(report, results, model_dir, cfg)
        (evaluation / "report.json").write_text(
            json.dumps(report, indent=2, default=float), encoding="utf-8"
        )
    print(f"winner: {winner}; wrote {model_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
