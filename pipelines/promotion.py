"""Promote and roll back MLflow aliases (PRD 16.3 last line, 16.4 step 5, 16.5).

Aliases only. ``promote`` moves ``production`` to a version and parks the old production version
under ``previous``. ``rollback`` swaps ``production`` and ``previous``, so a second rollback
undoes the first. The ML service notices the change at its next poll; nothing is rebuilt.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

from pipelines.data_steps import PipelineError

PRODUCTION, PREVIOUS, CANDIDATE = "production", "previous", "candidate"
ROLLBACK_LOG = Path("docs/ops/rollback-log.md")
_LOG_HEADER = (
    "# Rollback log\n\n"
    "One row per promotion or rollback (PRD 16.5). Versions are MLflow registry versions.\n\n"
    "| When (UTC) | Action | Model | From | To | Actor | Reason |\n"
    "|---|---|---|---|---|---|---|\n"
)


@dataclass(frozen=True)
class AliasChange:
    action: str
    model: str
    from_version: str | None
    to_version: str
    previous_version: str | None


def default_tracking_uri() -> str:
    return os.environ.get("MLFLOW_TRACKING_URI") or "sqlite:///data/mlflow/mlflow.db"


def open_client(tracking_uri: str | None = None) -> MlflowClient:
    uri = tracking_uri or default_tracking_uri()
    return MlflowClient(uri, uri)


def _alias_version(client: MlflowClient, model: str, alias: str) -> str | None:
    try:
        return str(client.get_model_version_by_alias(model, alias).version)
    except mlflow.exceptions.MlflowException:
        return None


def _now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def _clean(text: str) -> str:
    return " ".join(text.replace("|", "/").split())


def _append_log(path: Path, change: AliasChange, actor: str, reason: str, when: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_LOG_HEADER, encoding="utf-8")
    row = (
        f"| {when} | {change.action} | {change.model} | {change.from_version or '-'} | "
        f"{change.to_version} | {_clean(actor)} | {_clean(reason) or '-'} |\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(row)


def _tag(client: MlflowClient, model: str, version: str, change: AliasChange, **extra: str) -> None:
    tags = {f"{change.action}_at": _now(), f"{change.action}_from": change.from_version or "none"}
    for key, value in {**tags, **extra}.items():
        client.set_model_version_tag(model, version, key, value)


def promote(
    client: MlflowClient,
    model: str,
    version: str,
    *,
    actor: str = "operator",
    reason: str = "",
    force: bool = False,
    log_path: Path | None = ROLLBACK_LOG,
) -> AliasChange:
    """Move ``production`` to ``version``. Only versions tagged ``gate=passed`` qualify."""
    try:
        target = client.get_model_version(model, str(version))
    except mlflow.exceptions.MlflowException as exc:
        raise PipelineError("VERSION_NOT_FOUND", f"{model} has no version {version}") from exc
    gate = (target.tags or {}).get("gate")
    if gate != "passed" and not force:
        raise PipelineError(
            "GATE_NOT_PASSED",
            f"{model} v{version} has gate={gate or 'unknown'}; "
            "fix the model, or pass --force with --reason",
        )
    if force and not reason.strip():
        raise PipelineError("REASON_REQUIRED", "--force needs --reason")
    current = _alias_version(client, model, PRODUCTION)
    number = str(target.version)
    if current == number:
        raise PipelineError("ALREADY_PRODUCTION", f"{model} v{number} already holds production")
    if current is not None:
        client.set_registered_model_alias(model, PREVIOUS, current)
    client.set_registered_model_alias(model, PRODUCTION, number)
    if _alias_version(client, model, CANDIDATE) == number:
        client.delete_registered_model_alias(model, CANDIDATE)
    change = AliasChange("promote", model, current, number, current)
    _tag(client, model, number, change, promote_by=_clean(actor), forced=str(force).lower())
    if log_path is not None:
        note = f"forced: {reason}" if force else reason
        _append_log(log_path, change, actor, note, _now())
    return change


def rollback(
    client: MlflowClient,
    model: str,
    *,
    actor: str = "operator",
    reason: str = "",
    log_path: Path | None = ROLLBACK_LOG,
) -> AliasChange:
    """Swap ``production`` and ``previous``. A reason is required: rollbacks are audited."""
    if not reason.strip():
        raise PipelineError("REASON_REQUIRED", "rollback needs --reason")
    current = _alias_version(client, model, PRODUCTION)
    previous = _alias_version(client, model, PREVIOUS)
    if previous is None:
        raise PipelineError("NO_PREVIOUS", f"{model} has no version with alias previous")
    if current is None:
        raise PipelineError("NO_PRODUCTION", f"{model} has no version with alias production")
    client.set_registered_model_alias(model, PRODUCTION, previous)
    client.set_registered_model_alias(model, PREVIOUS, current)
    change = AliasChange("rollback", model, current, previous, current)
    _tag(client, model, previous, change, rollback_reason=_clean(reason), rollback_by=_clean(actor))
    _tag(client, model, current, change, rolled_back_reason=_clean(reason))
    if log_path is not None:
        _append_log(log_path, change, actor, reason, _now())
    return change
