"""``shadow-evaluate`` (PRD 15.1, 16.4): evaluate the candidate on shadow logs and promote it."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mlflow.tracking import MlflowClient

from pipelines import promotion
from pipelines.data_steps import PipelineError
from pipelines.shadow import logs
from pipelines.shadow.config import ShadowConfig, load_config
from pipelines.shadow.evaluate import PASSED, ShadowReport, evaluate

ACTOR = "shadow-evaluate"


def alias_version(client: MlflowClient, model: str, alias: str) -> str:
    try:
        return str(client.get_model_version_by_alias(model, alias).version)
    except Exception as exc:
        raise PipelineError("ALIAS_NOT_SET", f"{model} has no alias `{alias}`") from exc


def run(
    *,
    client: MlflowClient,
    model: str,
    log_files: Iterable[Path],
    corrections_file: Path | None,
    reports_dir: Path,
    today: dt.date,
    promote: bool = True,
    cfg: ShadowConfig | None = None,
    log_path: Path | None = promotion.ROLLBACK_LOG,
) -> tuple[ShadowReport, dict[str, Any]]:
    """Evaluate, write ``<reports_dir>/shadow/<date>.json`` and promote when every criterion holds.

    Returns the report and a small dict with the promotion result (``promoted`` and, when the
    registry refused it, ``refused``).
    """
    cfg = cfg or load_config()
    candidate = alias_version(client, model, promotion.CANDIDATE)
    production = alias_version(client, model, promotion.PRODUCTION)
    if candidate == production:
        raise PipelineError(
            "NO_CANDIDATE", f"{model} candidate and production are both v{production}"
        )
    predictions, errors = logs.read_files(log_files)
    since = dt.datetime.combine(today, dt.time.min, tzinfo=dt.UTC) - dt.timedelta(
        days=cfg.lookback_days
    )
    predictions = predictions[predictions["logged_at"] >= since]
    errors = errors[errors["logged_at"] >= since]
    corrections = logs.read_corrections(corrections_file) if corrections_file else {}
    report = evaluate(
        predictions,
        errors,
        corrections,
        production_version=f"{model}@{production}",
        candidate_version=f"{model}@{candidate}",
        cfg=cfg,
    )
    outcome: dict[str, Any] = {"promoted": False}
    if promote and report.outcome == PASSED:
        try:
            promotion.promote(
                client,
                model,
                candidate,
                actor=ACTOR,
                reason=f"shadow criteria met ({cfg.version})",
                log_path=log_path,
            )
            outcome["promoted"] = True
        except PipelineError as exc:  # for example gate != passed: the human decides
            outcome["refused"] = f"{exc.code}: {exc}"
    out = reports_dir / "shadow"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{today.isoformat()}.json").write_text(
        json.dumps({**report.as_dict(), **outcome}, indent=2, default=float), encoding="utf-8"
    )
    return report, outcome
