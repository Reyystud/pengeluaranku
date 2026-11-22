"""Drift computation: Evidently report + unseen-merchant share (PRD 18.1, 18.3).

Reference = the sample stored with the production model; current = the last ``window_days`` of
prediction logs. Thresholds come from ``config/drift.yaml``. Nothing here reads text or user ids:
the inputs are the feature summary columns of the prediction log and a merchant hash.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

from pipelines.drift import evidently_compat
from pipelines.drift.config import DriftConfig

evidently_compat.ensure()

from evidently import DataDefinition, Dataset, Report  # noqa: E402
from evidently.presets import DataDriftPreset  # noqa: E402


@dataclass
class DriftSummary:
    report_date: str
    config_version: str
    model_version: str
    status: str  # ok | drift | skipped
    reason: str = ""
    reference_rows: int = 0
    current_rows: int = 0
    window_start: str = ""
    window_end: str = ""
    psi: dict[str, float] = field(default_factory=dict)
    psi_max: float | None = None
    drifted_features: list[str] = field(default_factory=list)
    unseen_merchant_share: float | None = None
    unseen_merchant_median_28d: float | None = None
    unseen_merchant_ratio: float | None = None
    unseen_merchant_alert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def unseen_share(current: pd.DataFrame, known: set[str]) -> float | None:
    """Share of predictions whose merchant hash is not in the training vocabulary.

    Rows without a merchant (null hash) are left out of both sides: no merchant, nothing unseen.
    """
    hashes = current["merchant_hash"].dropna()
    if hashes.empty:
        return None
    return float((~hashes.isin(known)).mean())


def unseen_alert(
    share: float | None, history: list[float], cfg: DriftConfig
) -> tuple[float | None, float | None, bool]:
    """(28-day median, ratio, alert). No alert without enough history or a positive median."""
    recent = history[-cfg.unseen_history_days :]
    if share is None or len(recent) < cfg.unseen_min_history:
        return None, None, False
    median = statistics.median(recent)
    if median <= 0:
        return median, None, False
    ratio = share / median
    return median, ratio, ratio > cfg.unseen_ratio_threshold


def _definition(cfg: DriftConfig) -> DataDefinition:
    return DataDefinition(
        numerical_columns=list(cfg.numeric_features),
        categorical_columns=list(cfg.categorical_features),
    )


def run_report(
    reference: pd.DataFrame, current: pd.DataFrame, cfg: DriftConfig
) -> tuple[Any, dict[str, float]]:
    """Evidently snapshot and the PSI per monitored column."""
    columns = [*cfg.numeric_features, *cfg.categorical_features]
    definition = _definition(cfg)
    snapshot = Report([DataDriftPreset(method="psi", threshold=cfg.psi_threshold)]).run(
        Dataset.from_pandas(current[columns].reset_index(drop=True), data_definition=definition),
        Dataset.from_pandas(reference[columns].reset_index(drop=True), data_definition=definition),
    )
    psi: dict[str, float] = {}
    for metric in snapshot.dict()["metrics"]:
        name = str(metric["metric_name"])
        if name.startswith("ValueDrift(column="):
            column = name.split("column=", 1)[1].split(",", 1)[0]
            psi[column] = float(metric["value"])
    return snapshot, psi


def summarize(
    *,
    report_date: dt.date,
    model_version: str,
    reference: pd.DataFrame,
    current: pd.DataFrame,
    known_merchants: set[str],
    unseen_history: list[float],
    cfg: DriftConfig,
    window: tuple[dt.datetime, dt.datetime],
) -> tuple[DriftSummary, Any | None]:
    """Summary of one day; the Evidently snapshot is ``None`` when the report was skipped."""
    summary = DriftSummary(
        report_date=report_date.isoformat(),
        config_version=cfg.version,
        model_version=model_version,
        status="ok",
        reference_rows=len(reference),
        current_rows=len(current),
        window_start=window[0].isoformat(),
        window_end=window[1].isoformat(),
    )
    if len(current) < cfg.min_rows:
        summary.status = "skipped"
        summary.reason = (
            f"only {len(current)} prediction rows in the window (minimum {cfg.min_rows})"
        )
        return summary, None
    snapshot, psi = run_report(reference, current, cfg)
    summary.psi = psi
    key = [psi[c] for c in cfg.key_features if c in psi]
    summary.psi_max = max(key) if key else None
    summary.drifted_features = sorted(
        c for c in cfg.key_features if psi.get(c, 0.0) > cfg.psi_threshold
    )
    share = unseen_share(current, known_merchants)
    median, ratio, alert = unseen_alert(share, unseen_history, cfg)
    summary.unseen_merchant_share = share
    summary.unseen_merchant_median_28d = median
    summary.unseen_merchant_ratio = ratio
    summary.unseen_merchant_alert = alert
    if summary.drifted_features or alert:
        summary.status = "drift"
    return summary, snapshot
