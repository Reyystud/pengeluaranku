"""Decide from shadow logs whether the candidate may replace production (PRD 16.4 item 4).

Pure functions: logs and corrections in, a report out. Nothing here reads MLflow or the clock.
Criteria (all must hold, thresholds in ``config/shadow.yaml``):

1. shadow period >= ``min_days`` and >= ``min_predictions`` mirrored predictions;
2. agreement with production >= ``agreement_min`` on items nobody corrected;
3. on corrected items, candidate accuracy >= production accuracy (+ margin);
4. candidate P95 latency within the SLO;
5. PSI of the predicted-category distribution, candidate vs production, below ``psi_max``;
6. shadow error rate at most ``max_error_rate``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from pipelines.shadow.config import ShadowConfig

INSUFFICIENT, REJECTED, PASSED = "insufficient_data", "rejected", "passed"


@dataclass(frozen=True)
class Criterion:
    name: str
    status: str  # pass | fail | insufficient
    value: float | None
    threshold: float | None
    detail: str = ""


@dataclass
class ShadowReport:
    outcome: str
    config_version: str
    production_version: str
    candidate_version: str
    shadow_predictions: int
    matched_items: int
    period_days: float
    criteria: list[Criterion] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def psi(production: pd.Series, candidate: pd.Series, epsilon: float) -> float:
    """Population stability index of two categorical samples (shares floored at ``epsilon``)."""
    cats = sorted(set(production) | set(candidate))
    p = production.value_counts(normalize=True).reindex(cats, fill_value=0.0).clip(lower=epsilon)
    q = candidate.value_counts(normalize=True).reindex(cats, fill_value=0.0).clip(lower=epsilon)
    return float(((q - p) * np.log(q / p)).sum())


def evaluate(
    predictions: pd.DataFrame,
    errors: pd.DataFrame,
    corrections: dict[str, str],
    *,
    production_version: str,
    candidate_version: str,
    cfg: ShadowConfig,
) -> ShadowReport:
    """``*_version`` are the labels in the logs (for example ``transaction-classifier@7``)."""
    prod = predictions[
        (~predictions["shadow"]) & (predictions["model_version"] == production_version)
    ]
    cand = predictions[predictions["shadow"] & (predictions["model_version"] == candidate_version)]
    cand_errors = errors[errors["model_version"] == candidate_version]
    keys = ["request_id", "input_hash"]
    joined = prod.drop_duplicates(keys).merge(
        cand.drop_duplicates(keys), on=keys, suffixes=("_prod", "_cand")
    )
    period = (
        float((cand["logged_at"].max() - cand["logged_at"].min()).total_seconds() / 86400)
        if len(cand)
        else 0.0
    )
    report = ShadowReport(
        outcome=INSUFFICIENT,
        config_version=cfg.version,
        production_version=production_version,
        candidate_version=candidate_version,
        shadow_predictions=len(cand),
        matched_items=len(joined),
        period_days=round(period, 3),
    )
    c = report.criteria
    enough_time = period >= cfg.min_days
    enough_rows = len(cand) >= cfg.min_predictions
    c.append(
        Criterion(
            "shadow_period_days", "pass" if enough_time else "insufficient", period, cfg.min_days
        )
    )
    c.append(
        Criterion(
            "shadow_predictions",
            "pass" if enough_rows else "insufficient",
            float(len(cand)),
            float(cfg.min_predictions),
        )
    )
    if not (enough_time and enough_rows) or joined.empty:
        return report  # nothing else is meaningful yet

    corrected_mask = joined["input_hash"].isin(corrections)
    plain = joined[~corrected_mask]
    agree = (
        float((plain["predicted_category_prod"] == plain["predicted_category_cand"]).mean())
        if len(plain)
        else float("nan")
    )
    c.append(
        Criterion(
            "agreement_non_corrected",
            "pass"
            if agree >= cfg.agreement_min
            else ("insufficient" if np.isnan(agree) else "fail"),
            None if np.isnan(agree) else agree,
            cfg.agreement_min,
            f"{len(plain)} items",
        )
    )

    corrected = joined[corrected_mask]
    if len(corrected) < cfg.min_corrected_items:
        c.append(
            Criterion(
                "corrected_accuracy",
                "insufficient" if cfg.require_corrections else "pass",
                None,
                float(cfg.min_corrected_items),
                f"{len(corrected)} corrected items; skipped"
                if not cfg.require_corrections
                else f"{len(corrected)} corrected items",
            )
        )
    else:
        truth = corrected["input_hash"].map(corrections)
        acc_prod = float((corrected["predicted_category_prod"] == truth).mean())
        acc_cand = float((corrected["predicted_category_cand"] == truth).mean())
        ok = acc_cand >= acc_prod + cfg.corrected_accuracy_margin
        c.append(
            Criterion(
                "corrected_accuracy",
                "pass" if ok else "fail",
                acc_cand - acc_prod,
                cfg.corrected_accuracy_margin,
                f"candidate {acc_cand:.4f} vs production {acc_prod:.4f} on {len(corrected)} items",
            )
        )

    p95 = float(np.percentile(cand["latency_ms"], 95))
    c.append(
        Criterion(
            "candidate_p95_latency_ms",
            "pass" if p95 <= cfg.p95_slo_ms else "fail",
            p95,
            cfg.p95_slo_ms,
        )
    )

    value = psi(
        joined["predicted_category_prod"], joined["predicted_category_cand"], cfg.psi_epsilon
    )
    c.append(
        Criterion("category_psi", "pass" if value < cfg.psi_max else "fail", value, cfg.psi_max)
    )

    rate = len(cand_errors) / (len(cand) + len(cand_errors))
    c.append(
        Criterion(
            "error_rate", "pass" if rate <= cfg.max_error_rate else "fail", rate, cfg.max_error_rate
        )
    )

    statuses = {x.status for x in c}
    if "fail" in statuses:
        report.outcome = REJECTED
    elif "insufficient" in statuses:
        report.outcome = INSUFFICIENT
    else:
        report.outcome = PASSED
    return report
