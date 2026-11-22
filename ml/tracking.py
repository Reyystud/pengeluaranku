"""Tiny MLflow helper for experiment runs that are not registered models (PRD 16).

Local runs go to ``data/mlflow`` (SQLite), like ``ml.classification.train``; set
``MLFLOW_TRACKING_URI`` to an ``http(s)`` server to log there instead.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def log_run(
    experiment: str,
    run_name: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    reports: dict[str, Any],
) -> str:
    """Create one run and return its ID. ``reports`` maps an artifact path to a JSON-able dict."""
    import mlflow

    remote = os.environ.get("MLFLOW_TRACKING_URI", "")
    artifact_location = None
    if remote.startswith(("http://", "https://")):
        mlflow.set_tracking_uri(remote)
    else:
        base = ROOT / "data" / "mlflow"
        base.mkdir(parents=True, exist_ok=True)
        mlflow.set_tracking_uri(f"sqlite:///{base / 'mlflow.db'}")
        artifact_location = (base / "artifacts").as_uri()
    exp = mlflow.get_experiment_by_name(experiment)
    exp_id = (
        exp.experiment_id
        if exp
        else mlflow.create_experiment(experiment, artifact_location=artifact_location)
    )
    with mlflow.start_run(experiment_id=exp_id, run_name=run_name) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
        for path, doc in reports.items():
            mlflow.log_dict(doc, path)
        return str(run.info.run_id)
