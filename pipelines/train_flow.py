"""Prefect flow ``train_model(model_name, dataset_version)`` (PRD 16.1).

Steps: load -> validate -> split check -> features -> train/calibrate/evaluate -> gate ->
log + register (alias ``candidate``) -> notify. Only the transaction classifier exists so far;
the other model names are added with their tasks (T-38, T-41).
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
from mlflow.tracking import MlflowClient

from ml.classification.behavioural import run_behavioural
from ml.classification.benchmark import latency_benchmark
from ml.classification.config import load_train_config
from ml.classification.data import load_split_frames
from ml.classification.train import MODEL_NAME, fit_candidates, write_run_dir
from pipelines import data_steps, gates, model_card, registry
from pipelines.data_steps import PipelineError

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "classifier"
SUPPORTED = (MODEL_NAME,)


@dataclass
class TrainResult:
    run_dir: Path
    mlflow_run_id: str
    gate: str  # passed | needs_review | failed
    registered_version: str | None
    gates: list[gates.GateResult] = field(default_factory=list)
    winner: str = ""
    test_macro_f1: float = 0.0


def git_state(root: Path) -> tuple[str, bool]:
    """Short commit and whether the working tree has uncommitted or untracked changes."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        return "unknown", True
    return commit or "unknown", bool(status) or not commit


# step "load-data"
def load_data(paths: data_steps.DatasetPaths) -> dict[str, Any]:
    manifest = data_steps.verify_manifest(paths)
    return {"rows": manifest["row_counts"]["transactions"]}


# step "validate"
def validate(
    paths: data_steps.DatasetPaths, cfg: dict[str, Any], quarantine_dir: Path
) -> data_steps.ValidationResult:
    knobs = cfg["pipeline"]
    return data_steps.validate_dataset(
        paths,
        float(knobs["max_quarantine_share"]),
        int(knobs["validation_batch_rows"]),
        quarantine_dir,
    )


# step "split"
def check_splits(paths: data_steps.DatasetPaths) -> dict[str, str]:
    return data_steps.verify_splits(paths)


# step "features"
def features(paths: data_steps.DatasetPaths, cfg: dict[str, Any]) -> int:
    return data_steps.feature_parity_sample(
        paths, int(cfg["pipeline"]["parity_sample_rows"]), int(cfg["seed"])
    )


# step "train-evaluate"
def train_and_evaluate(
    cfg: dict[str, Any], names: list[str], root: Path, out_dir: Path, commit: str
) -> tuple[dict[str, Any], Path, dict[str, dict[str, Any]], float]:
    started = time.perf_counter()
    ds = cfg["dataset"]
    frames = load_split_frames(root / ds["data_dir"], root / ds["assignments"])
    results = fit_candidates(cfg, frames, names)
    report, model_dir = write_run_dir(cfg, frames, results, out_dir, git_commit=commit, root=root)
    winner_artifacts = results[report["selection"]["winner"]]["_artifacts"]
    report["behavioural"] = run_behavioural(winner_artifacts, cfg["behavioural"])
    report["latency_benchmark"] = latency_benchmark(winner_artifacts, cfg["benchmark"])
    (model_dir / "evaluation" / "report.json").write_text(
        json.dumps(report, indent=2, default=float), encoding="utf-8"
    )
    public = {k: {a: b for a, b in v.items() if not a.startswith("_")} for k, v in results.items()}
    return report, model_dir, public, time.perf_counter() - started


# step "gate"
def gate(
    report: dict[str, Any],
    cfg: dict[str, Any],
    dirty: bool,
    mlflow_dir: Path,
    explicit_dir: bool,
) -> list[gates.GateResult]:
    winner = report["selection"]["winner"]
    baseline = report["selection"]["baseline"]
    client, _ = _experiment(mlflow_dir, explicit_dir)
    with tempfile.TemporaryDirectory() as tmp:
        reference = registry.fetch_production(client, MODEL_NAME, Path(tmp))
    test = report["models"][winner]["test"]
    base_test = report["models"].get(baseline, {}).get("test", {})
    return gates.run_gates(
        gates.GateInputs(
            dirty=dirty,
            seed=cfg.get("seed"),
            winner=winner,
            baseline=baseline,
            test_ece=float(test["ece"]),
            test_macro_f1=float(test["macro_f1"]),
            split_hash=report["dataset"]["split_hash"],
            slices=gates.slice_scores(test),
            baseline_slices=gates.slice_scores(base_test),
            behavioural=report["behavioural"],
            latency=report["latency_benchmark"],
            reference=reference,
            knobs=cfg["gates"],
        )
    )


def _experiment(mlflow_dir: Path, explicit: bool) -> tuple[MlflowClient, str]:
    """Open the experiment. ``MLFLOW_TRACKING_URI`` (a remote server) wins unless a directory
    was passed explicitly; ``mlflow.set_tracking_uri`` writes that variable, so it is not read
    again after this process has set it for another directory."""
    mlflow_dir.mkdir(parents=True, exist_ok=True)
    env = None if explicit else os.environ.get("MLFLOW_TRACKING_URI")
    uri = env or f"sqlite:///{mlflow_dir / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_registry_uri(uri)
    client = MlflowClient(uri, uri)
    exp = client.get_experiment_by_name(EXPERIMENT)
    if exp is not None:
        return client, exp.experiment_id
    artifacts = (mlflow_dir / "artifacts").resolve().as_uri()
    return client, client.create_experiment(EXPERIMENT, artifact_location=artifacts)


# step "register"
def log_and_register(
    *,
    report: dict[str, Any],
    results: dict[str, dict[str, Any]],
    model_dir: Path,
    cfg: dict[str, Any],
    gate_results: list[gates.GateResult],
    dirty: bool,
    seconds: float,
    mlflow_dir: Path,
    explicit_dir: bool,
    register: bool,
) -> tuple[str, str | None, str]:
    """Steps 8-10: one parent run with a child per candidate; register only a gated clean run."""
    client, experiment_id = _experiment(mlflow_dir, explicit_dir)
    passed = gates.gates_passed(gate_results)
    gate_tag = gates.gate_outcome(gate_results)
    winner = report["selection"]["winner"]
    seed = int(cfg["seed"])
    metadata: dict[str, Any] = json.loads((model_dir / "metadata.json").read_text())
    metadata = registry.complete_metadata(metadata, report, gate_results, seed, None)
    registry.write_metadata(model_dir, metadata)
    version: str | None = None
    with mlflow.start_run(experiment_id=experiment_id, run_name=f"train-{report['run_id']}") as run:
        run_id = run.info.run_id
        mlflow.log_params(
            {
                "model_name": MODEL_NAME,
                "winner": winner,
                "seed": seed,
                "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
                "dataset_name": "synthetic",
                "dataset_version": report["dataset"]["version"],
                "dataset_sha256": report["dataset"]["transactions_sha256"],
                "split_hash": report["dataset"]["split_hash"],
                "feature_version": report["feature_version"],
                "taxonomy_version": report["taxonomy_version"],
                "config_version": cfg["version"],
                "git_commit": report["git_commit"],
            }
        )
        mlflow.set_tags({"dirty": str(dirty).lower(), "gate": gate_tag, "pipeline": "prefect"})
        w = report["models"][winner]
        mlflow.log_metrics(
            {
                "test_macro_f1": w["test"]["macro_f1"],
                "test_ece": w["test"]["ece"],
                "unseen_macro_f1": w["test_unseen_merchant"]["macro_f1"],
                "training_seconds": seconds,
            }
        )
        for name, res in results.items():
            with mlflow.start_run(experiment_id=experiment_id, run_name=name, nested=True):
                mlflow.log_params({"model": name, "train_rows": res["train_rows"]})
                mlflow.log_metrics(
                    {
                        "val_macro_f1": res["validation"]["macro_f1"],
                        "test_macro_f1": res["test"]["macro_f1"],
                        "unseen_macro_f1": res["test_unseen_merchant"]["macro_f1"],
                        "fit_seconds": res["fit_seconds"],
                    }
                )
        mlflow.log_text(registry.pip_freeze(), "environment/pip_freeze.txt")
        mlflow.log_dict(
            {"gates": [g.__dict__ for g in gate_results], "passed": passed}, "gates.json"
        )
        card = model_card.render_model_card(report, metadata, gate_results, run_id, None)
        (model_dir / "model_card.md").write_text(card, encoding="utf-8")
        mlflow.log_artifacts(str(model_dir), artifact_path="model")
        if register and passed and not dirty:
            version = registry.register_candidate(
                client, MODEL_NAME, run_id, model_dir, metadata, gate_tag
            )
            card = model_card.render_model_card(report, metadata, gate_results, run_id, version)
            (model_dir / "model_card.md").write_text(card, encoding="utf-8")
            client.log_artifact(run_id, str(model_dir / "model_card.md"), artifact_path="model")
        summary = model_card.render_summary(report, gate_results, version, dirty)
        mlflow.log_text(summary, "summary.md")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")  # step 10, when run in CI
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as fh:
            fh.write(summary + "\n")
    return run_id, version, summary


Runner = Callable[..., Any]  # run(step_name, fn, *args, **kwargs) -> fn(*args, **kwargs)


def run_inline(_name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a step directly (no orchestrator): tests and ``--orchestrator none``."""
    return fn(*args, **kwargs)


def run_training(
    model_name: str,
    dataset_version: str,
    *,
    run: Runner = run_inline,
    log: Callable[[str], None] = print,
    models: list[str] | None = None,
    max_rows_per_class: int | None = None,
    config_path: str | None = None,
    root: str = str(ROOT),
    mlflow_dir: str | None = None,
    register: bool = True,
) -> TrainResult:
    """The pipeline of PRD 16.1. ``run`` wraps each step (a Prefect task or a plain call)."""
    if model_name not in SUPPORTED:
        raise PipelineError("MODEL_UNSUPPORTED", f"{model_name!r} has no training task yet")
    base = Path(root)
    cfg = load_train_config(Path(config_path) if config_path else None)
    if max_rows_per_class is not None:
        cfg["sampling"]["max_rows_per_class"] = max_rows_per_class
    paths = data_steps.dataset_paths(base, dataset_version)
    cfg["dataset"] = {
        "data_dir": f"data/{dataset_version}",
        "assignments": f"data/splits/{dataset_version}/assignments.parquet",
        "dataset_version": dataset_version,
    }
    seed = int(cfg["seed"])
    random.seed(seed)
    np.random.seed(seed)
    commit, dirty = git_state(base)
    if dirty:
        log("working tree is dirty: the run is logged but cannot be registered")

    log("step 1 load")
    run("load-data", load_data, paths)
    log("step 2 validate")
    validation = run("validate", validate, paths, cfg, base / "data" / "quarantine")
    log(f"validated {validation.rows} rows, {validation.quarantined} quarantined")
    log("step 3 split")
    run("split", check_splits, paths)
    log("step 4 features")
    run("features", features, paths, cfg)
    log("steps 5-7 train, calibrate, evaluate")
    names = models or ["logreg", "linear_svm", "lightgbm"]
    report, model_dir, results, seconds = run(
        "train-evaluate", train_and_evaluate, cfg, names, base, base / "models" / MODEL_NAME, commit
    )
    log("step 8 gate")
    gate_results = run(
        "gate",
        gate,
        report,
        cfg,
        dirty,
        Path(mlflow_dir) if mlflow_dir else base / "data" / "mlflow",
        mlflow_dir is not None,
    )
    log("steps 9-10 register and notify")
    run_id, version, summary = run(
        "register",
        log_and_register,
        report=report,
        results=results,
        model_dir=model_dir,
        cfg=cfg,
        gate_results=gate_results,
        dirty=dirty,
        seconds=seconds,
        mlflow_dir=Path(mlflow_dir) if mlflow_dir else base / "data" / "mlflow",
        explicit_dir=mlflow_dir is not None,
        register=register,
    )
    print(summary)
    winner = report["selection"]["winner"]
    return TrainResult(
        run_dir=model_dir,
        mlflow_run_id=run_id,
        gate=gates.gate_outcome(gate_results),
        registered_version=version,
        gates=gate_results,
        winner=winner,
        test_macro_f1=float(report["models"][winner]["test"]["macro_f1"]),
    )


def prefect_runner(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run one step as a Prefect task (needs a Prefect API; see ``make prefect-server``)."""
    from prefect import task
    from prefect.cache_policies import NO_CACHE

    return task(name=name, cache_policy=NO_CACHE, persist_result=False)(fn)(*args, **kwargs)


def build_flow() -> Any:
    """The Prefect flow ``train_model`` (PRD 16.1): the same ``run_training`` with task steps.

    Built on demand so that importing this module never needs Prefect or its server.
    """
    from prefect import flow, get_run_logger

    @flow(name="train_model", persist_result=False)
    def train_model(
        model_name: str,
        dataset_version: str,
        models: list[str] | None = None,
        max_rows_per_class: int | None = None,
        config_path: str | None = None,
        root: str = str(ROOT),
        mlflow_dir: str | None = None,
        register: bool = True,
    ) -> TrainResult:
        return run_training(
            model_name,
            dataset_version,
            run=prefect_runner,
            log=get_run_logger().info,
            models=models,
            max_rows_per_class=max_rows_per_class,
            config_path=config_path,
            root=root,
            mlflow_dir=mlflow_dir,
            register=register,
        )

    return train_model
