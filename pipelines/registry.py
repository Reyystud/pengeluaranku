"""MLflow registry helpers: register a gated run as alias ``candidate`` (PRD 16.1 step 9, 16.7).

Aliases only (``production`` / ``candidate`` / ``previous``), never stages. This module never
moves ``production``; promotion is T-27.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

from pipelines.gates import GateResult, Reference, slice_scores

CANDIDATE = "candidate"


def runtime_info() -> dict[str, str]:
    info = {"python": platform.python_version()}
    for pkg in ("scikit-learn", "lightgbm", "numpy", "pandas", "mlflow", "joblib"):
        try:
            info[pkg] = version(pkg)
        except PackageNotFoundError:
            info[pkg] = "unknown"
    return info


def pip_freeze() -> str:
    out = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True, check=False
    )
    if out.returncode == 0 and out.stdout.strip():
        return out.stdout
    uv = subprocess.run(["uv", "pip", "freeze"], capture_output=True, text=True, check=False)
    return uv.stdout if uv.returncode == 0 else "unavailable\n"


def semantic_version(mlflow_version: str) -> str:
    """No release process yet: ``0.<registry version>.0`` keeps ordering and stays honest."""
    return f"0.{int(mlflow_version)}.0"


def complete_metadata(
    metadata: dict[str, Any],
    report: dict[str, Any],
    gates: list[GateResult],
    seed: int,
    mlflow_version: str | None,
) -> dict[str, Any]:
    """Add the PRD 11.6 fields that only exist after the run (metrics, gates, registry version)."""
    winner = report["selection"]["winner"]
    test = report["models"][winner]["test"]
    unseen = report["models"][winner]["test_unseen_merchant"]
    return {
        **metadata,
        "mlflow_version": mlflow_version,
        "semantic_version": None if mlflow_version is None else semantic_version(mlflow_version),
        "seed": seed,
        "metrics": {
            "macro_f1_test": test["macro_f1"],
            "ece_test": test["ece"],
            "macro_f1_unseen_merchant": unseen["macro_f1"],
            "golden_accuracy": (report.get("behavioural") or {}).get("golden_accuracy"),
            "latency_p95_ms": (report.get("latency_benchmark") or {}).get("p95_ms"),
        },
        "gates": [{"name": g.name, "status": g.status, "detail": g.detail} for g in gates],
        "priors": None,
        "runtime": runtime_info(),
    }


def write_metadata(model_dir: Path, metadata: dict[str, Any]) -> None:
    (model_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def register_candidate(
    client: MlflowClient,
    model_name: str,
    run_id: str,
    model_dir: Path,
    metadata: dict[str, Any],
    gate_tag: str,
) -> str:
    """Create a model version from the run's ``model`` artifacts and move ``candidate`` to it.

    ``metadata.json`` is rewritten once the registry version is known and logged again, so the
    artifact the ML service loads carries its own ``mlflow_version``.
    """
    try:
        client.create_registered_model(model_name)
    except mlflow.exceptions.MlflowException:
        pass  # already exists
    created = client.create_model_version(
        model_name, source=f"runs:/{run_id}/model", run_id=run_id, tags={"gate": gate_tag}
    )
    number = str(created.version)
    metadata = {**metadata, "mlflow_version": number, "semantic_version": semantic_version(number)}
    write_metadata(model_dir, metadata)
    client.log_artifact(run_id, str(model_dir / "metadata.json"), artifact_path="model")
    client.set_registered_model_alias(model_name, CANDIDATE, number)
    return number


def fetch_production(client: MlflowClient, model_name: str, tmp: Path) -> Reference | None:
    """Evidence of the version holding alias ``production``; ``None`` when there is none."""
    try:
        version = client.get_model_version_by_alias(model_name, "production")
    except mlflow.exceptions.MlflowException:
        return None
    run_id = version.run_id
    if run_id is None:
        return None
    try:
        meta_path = client.download_artifacts(run_id, "model/metadata.json", str(tmp))
        report_path = client.download_artifacts(run_id, "model/evaluation/report.json", str(tmp))
    except mlflow.exceptions.MlflowException:
        return None
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    winner = report["selection"]["winner"]
    test = report["models"][winner]["test"]
    metrics = meta.get("metrics") or {}
    return Reference(
        version=str(version.version),
        split_hash=(meta.get("dataset") or {}).get("split_hash"),
        test_macro_f1=metrics.get("macro_f1_test", test.get("macro_f1")),
        slices=slice_scores(test),
        golden_accuracy=metrics.get("golden_accuracy"),
    )
