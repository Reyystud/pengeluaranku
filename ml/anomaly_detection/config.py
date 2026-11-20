"""Typed view of ``config/anomaly.yaml`` (PRD 7.6, 0.3 rule 3: no hardcoded thresholds)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ml.config import _load_yaml


@dataclass(frozen=True)
class AnomalyConfig:
    version: str
    feature_version: str
    # amount_spike
    z_threshold: float
    z_scale: float
    mad_floor: float
    min_alert_amount: float
    min_ratio_to_typical: float
    spike_score_offset: float
    spike_score_divisor: float
    spike_high_z: float
    history_days: int
    low_z_threshold: float
    # frequency_burst
    burst_min_count: int
    burst_max_tail: float
    burst_high_tail: float
    burst_score_divisor: float
    burst_rate_days: int
    burst_min_rate: float
    # new_merchant_high_value
    new_merchant_min_amount: float
    new_merchant_p95_multiplier_high: float
    new_merchant_score_medium: float
    new_merchant_score_high: float
    # category_surge
    surge_window_days: int
    surge_baseline_weeks: int
    surge_min_weeks_with_spend: int
    surge_min_ratio: float
    surge_min_excess: float
    surge_score_divisor: float
    surge_high_ratio: float
    # cold start and alerts
    min_category_history: int
    min_history_days: int
    limited_max_severity: str
    alerts_per_period: int
    alert_max_age_days: int
    suppression_days: int
    max_reasons: int
    max_events_per_drain: int


def _from_mapping(d: dict[str, Any]) -> AnomalyConfig:
    s, lo, b, n = (
        d["amount_spike"],
        d["amount_low"],
        d["frequency_burst"],
        d["new_merchant_high_value"],
    )
    g, c, a, r = d["category_surge"], d["cold_start"], d["alerts"], d["reasons"]
    return AnomalyConfig(
        version=str(d["version"]),
        feature_version=str(d["feature_version"]),
        z_threshold=float(s["z_threshold"]),
        z_scale=float(s["z_scale"]),
        mad_floor=float(s["mad_floor"]),
        min_alert_amount=float(s["min_alert_amount"]),
        min_ratio_to_typical=float(s["min_ratio_to_typical"]),
        spike_score_offset=float(s["score_offset"]),
        spike_score_divisor=float(s["score_divisor"]),
        spike_high_z=float(s["high_z"]),
        history_days=int(s["history_days"]),
        low_z_threshold=float(lo["z_threshold"]),
        burst_min_count=int(b["min_count"]),
        burst_max_tail=float(b["max_tail_probability"]),
        burst_high_tail=float(b["high_tail_probability"]),
        burst_score_divisor=float(b["score_divisor"]),
        burst_rate_days=int(b["rate_days"]),
        burst_min_rate=float(b["min_rate_per_day"]),
        new_merchant_min_amount=float(n["min_amount"]),
        new_merchant_p95_multiplier_high=float(n["p95_multiplier_high"]),
        new_merchant_score_medium=float(n["score_medium"]),
        new_merchant_score_high=float(n["score_high"]),
        surge_window_days=int(g["window_days"]),
        surge_baseline_weeks=int(g["baseline_weeks"]),
        surge_min_weeks_with_spend=int(g["min_weeks_with_spend"]),
        surge_min_ratio=float(g["min_ratio"]),
        surge_min_excess=float(g["min_excess_amount"]),
        surge_score_divisor=float(g["score_divisor"]),
        surge_high_ratio=float(g["high_ratio"]),
        min_category_history=int(c["min_category_history"]),
        min_history_days=int(c["min_history_days"]),
        limited_max_severity=str(c["limited_max_severity"]),
        alerts_per_period=int(a["per_period_cap"]),
        alert_max_age_days=int(a["max_age_days"]),
        suppression_days=int(a["suppression_days"]),
        max_reasons=int(r["max_reasons"]),
        max_events_per_drain=int(d["dispatch"]["max_events_per_drain"]),
    )


@lru_cache(maxsize=1)
def load_anomaly_config() -> AnomalyConfig:
    return _from_mapping(_load_yaml("anomaly.yaml"))


@lru_cache(maxsize=1)
def load_category_priors() -> dict[str, tuple[float, float]]:
    """Per-category (median log1p amount, MAD) across users, from ``config/anomaly_priors.yaml``.

    The file is written by ``python -m ml.anomaly_detection.priors`` from a real dataset run; an
    empty mapping means limited-history users get no amount-spike detection (never made-up numbers).
    """
    try:
        data = _load_yaml("anomaly_priors.yaml")
    except FileNotFoundError:
        return {}
    return {
        str(k): (float(v["median"]), float(v["mad"])) for k, v in data.get("categories", {}).items()
    }
