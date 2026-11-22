"""``drift-report`` job (PRD 15.1, 18.3): one idempotent run per report date.

Re-running a date overwrites that day's ``summary.json`` and ``report.html``. The run logs one
``drift_summary`` line (numbers and feature names only); Cloud Monitoring turns its ``psi_max``
into a log-based metric.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

from ml.monitoring import REFERENCE_DIR, load_reference
from pipelines.data_steps import PipelineError
from pipelines.drift.config import DriftConfig
from pipelines.drift.report import DriftSummary, summarize
from pipelines.drift.sources import LogSource
from pipelines.drift.store import ReportStore

log = logging.getLogger("pipelines.drift")


def fetch_reference(client: MlflowClient, model_name: str, tmp: Path) -> tuple[Path, str]:
    """Download ``reference/`` of the production version; returns (folder, version)."""
    try:
        version = client.get_model_version_by_alias(model_name, "production")
    except mlflow.exceptions.MlflowException as exc:
        raise PipelineError(
            "NO_PRODUCTION", f"no production version of {model_name}: nothing to compare to"
        ) from exc
    if version.run_id is None:
        raise PipelineError("NO_RUN", f"production version {version.version} has no run")
    try:
        folder = client.download_artifacts(version.run_id, f"model/{REFERENCE_DIR}", str(tmp))
    except mlflow.exceptions.MlflowException as exc:
        raise PipelineError(
            "NO_REFERENCE",
            f"production version {version.version} has no reference sample: retrain it "
            "(models trained before T-35 do not store one)",
        ) from exc
    return Path(folder), f"{model_name}@{version.version}"


def run_drift_report(
    *,
    report_date: dt.date,
    reference_dir: Path,
    model_version: str,
    source: LogSource,
    store: ReportStore,
    cfg: DriftConfig,
) -> DriftSummary:
    end = dt.datetime.combine(report_date, dt.time.min, tzinfo=dt.UTC)
    start = end - dt.timedelta(days=cfg.window_days)
    reference, known = load_reference(reference_dir)
    current = source.fetch(start, end)
    history = store.history(report_date, cfg.unseen_history_days)
    summary, snapshot = summarize(
        report_date=report_date,
        model_version=model_version,
        reference=reference,
        current=current,
        known_merchants=known,
        unseen_history=history,
        cfg=cfg,
        window=(start, end),
    )
    html: str | None = None
    if snapshot is not None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.html"
            snapshot.save_html(str(target))
            html = target.read_text(encoding="utf-8")
    where = store.save(report_date, html, summary.to_dict())
    _log(summary, where)
    return summary


def _log(summary: DriftSummary, where: str) -> None:
    line: dict[str, Any] = {
        "event": "drift_summary",
        "status": summary.status,
        "report_date": summary.report_date,
        "model_version": summary.model_version,
        "current_rows": summary.current_rows,
        "psi_max": summary.psi_max,
        "drifted_features": summary.drifted_features,
        "unseen_merchant_share": summary.unseen_merchant_share,
        "unseen_merchant_ratio": summary.unseen_merchant_ratio,
        "unseen_merchant_alert": summary.unseen_merchant_alert,
        "report": where,
    }
    log.warning(json.dumps(line)) if summary.status == "drift" else log.info(json.dumps(line))
