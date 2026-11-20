"""Baseline detector (PRD 7.6.2 - 7.6.5). Pure functions: history in, detections out.

Everything here sees only what the caller passes in. The caller must build the history from rows
strictly before the transaction (PRD 11.1 rule 2); ``ml.features.testing.assert_point_in_time`` is
used by the tests to prove that for the backend's SQL and for the evaluation helper.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from ml.anomaly_detection.config import AnomalyConfig
from ml.anomaly_detection.stats import (
    clip01,
    mad,
    median,
    modified_z,
    percent_rank,
    percentile,
    poisson_sf,
)

AnomalyType = Literal[
    "amount_spike", "frequency_burst", "new_merchant_high_value", "category_surge", "amount_low"
]
Severity = Literal["low", "medium", "high"]
HistoryLevel = Literal["personal", "limited"]
_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class Reason:
    """FR-06.03 / 7.6.5: computed from the features that drove the score, never fixed text."""

    code: str
    feature: str
    value: float
    reference: float
    message: str


@dataclass(frozen=True)
class Detection:
    anomaly_type: AnomalyType
    score: float  # 0..1
    severity: Severity
    history_level: HistoryLevel
    reasons: tuple[Reason, ...]
    z: float | None = None


@dataclass(frozen=True)
class Transaction:
    """The transaction being scored."""

    amount: Decimal
    category_name: str
    merchant_key: str
    merchant_name: str


@dataclass(frozen=True)
class CategoryPrior:
    """Global (all users) median and MAD of ``log1p(amount)`` for one category (7.6.4)."""

    median: float
    mad: float


@dataclass(frozen=True)
class UserHistory:
    """Features of 11.2.2, from rows strictly before the transaction."""

    category_amounts: Sequence[float] = ()  # same category, last 180 days
    merchant_amounts: Sequence[float] = ()  # same merchant_key, last 180 days
    merchant_seen: bool = False  # any earlier transaction at this merchant_key
    expense_p95: float | None = None  # P95 of the user's expense amounts, last 180 days
    expense_count: int = 0  # all earlier expenses of the user
    category_count_24h: int = 0  # earlier ones in the category, in the 24 h before t (t excluded)
    category_count_rate_window: int = 0  # earlier ones in the category over the rate window
    history_days: float = 0.0  # age of the user's oldest earlier transaction
    prior: CategoryPrior | None = None


def idr(value: float) -> str:
    """``45000`` -> ``Rp45.000`` (display only; the float never leaves this module)."""
    return "Rp" + f"{round(value):,}".replace(",", ".")


def _cap(severity: Severity, level: HistoryLevel, cfg: AnomalyConfig) -> Severity:
    if level == "limited" and _RANK[severity] > _RANK[cfg.limited_max_severity]:
        return cfg.limited_max_severity  # type: ignore[return-value]
    return severity


def _limited_reason(cfg: AnomalyConfig, n: int) -> Reason:
    return Reason(
        "LIMITED_HISTORY",
        "history_n_cat",
        float(n),
        float(cfg.min_category_history),
        "Based on typical spending for this category (limited personal history)",
    )


def detect(tx: Transaction, h: UserHistory, cfg: AnomalyConfig) -> list[Detection]:
    """Per-transaction rules: amount spike (and low amount), frequency burst, new merchant."""
    out: list[Detection] = []
    spike = _amount(tx, h, cfg)
    if spike is not None:
        out.append(spike)
    burst = _burst(tx, h, cfg)
    if burst is not None:
        out.append(burst)
    new = _new_merchant(tx, h, cfg)
    if new is not None:
        out.append(new)
    return out


def _amount(tx: Transaction, h: UserHistory, cfg: AnomalyConfig) -> Detection | None:
    amount = float(tx.amount)
    n_cat = len(h.category_amounts)
    logs = [math.log1p(v) for v in h.category_amounts]
    if n_cat >= cfg.min_category_history:
        m, spread, level = median(logs), mad(logs), "personal"
    elif h.prior is not None:
        m, spread, level = h.prior.median, h.prior.mad, "limited"
    else:
        return None  # no personal history and no prior: say nothing rather than guess
    x = math.log1p(amount)
    z = modified_z(x, m, spread, cfg.mad_floor, cfg.z_scale)
    typical = math.exp(m)
    level_t: HistoryLevel = "personal" if level == "personal" else "limited"

    if z <= cfg.low_z_threshold and level_t == "personal":
        return Detection(
            "amount_low",
            clip01((-z - cfg.spike_score_offset) / cfg.spike_score_divisor),
            "low",
            level_t,
            (
                Reason(
                    "AMOUNT_VS_CATEGORY",
                    "ratio_to_cat_median",
                    amount / typical,
                    1.0,
                    f"{amount / typical:.1f}× your typical {tx.category_name} spending "
                    f"({idr(typical)})",
                ),
            ),
            z,
        )
    flagged = (
        z >= cfg.z_threshold
        and amount >= cfg.min_alert_amount
        and amount >= cfg.min_ratio_to_typical * typical
    )
    if not flagged:
        return None
    severity = _cap("high" if z >= cfg.spike_high_z else "medium", level_t, cfg)
    ratio = amount / typical
    reasons = [
        Reason(
            "AMOUNT_VS_CATEGORY",
            "ratio_to_cat_median",
            ratio,
            typical,
            f"{ratio:.1f}× your typical {tx.category_name} spending ({idr(typical)})",
        )
    ]
    if level_t == "personal":
        rank = percent_rank(amount, h.category_amounts)
        reasons.append(
            Reason(
                "AMOUNT_PERCENTILE",
                "pct_rank_cat",
                rank,
                100.0,
                f"Higher than {rank:.0f}% of your {tx.category_name} transactions",
            )
        )
    if len(h.merchant_amounts) >= 3:
        usual = median(list(h.merchant_amounts))
        if usual > 0 and amount / usual >= cfg.min_ratio_to_typical:
            reasons.append(
                Reason(
                    "AMOUNT_VS_MERCHANT",
                    "ratio_to_merchant_median",
                    amount / usual,
                    usual,
                    f"{amount / usual:.1f}× what you usually spend at {tx.merchant_name}",
                )
            )
    if level_t == "limited":
        reasons.append(_limited_reason(cfg, n_cat))
    score = clip01((z - cfg.spike_score_offset) / cfg.spike_score_divisor)
    return Detection("amount_spike", score, severity, level_t, tuple(reasons[: cfg.max_reasons]), z)


def _burst(tx: Transaction, h: UserHistory, cfg: AnomalyConfig) -> Detection | None:
    k = h.category_count_24h + 1  # the transaction itself counts
    if k < cfg.burst_min_count:
        return None
    lam = max(h.category_count_rate_window / cfg.burst_rate_days, cfg.burst_min_rate)
    p = poisson_sf(k, lam)
    if p >= cfg.burst_max_tail:
        return None
    level: HistoryLevel = (
        "personal" if len(h.category_amounts) >= cfg.min_category_history else "limited"
    )
    severity = _cap("high" if p < cfg.burst_high_tail else "medium", level, cfg)
    reasons = [
        Reason(
            "FREQUENCY_BURST",
            "cat_count_24h",
            float(k),
            lam,
            f"{k} {tx.category_name} transactions in 24 hours (usually about {lam:.1f})",
        )
    ]
    if level == "limited":
        reasons.append(_limited_reason(cfg, len(h.category_amounts)))
    score = clip01(-math.log10(max(p, 1e-300)) / cfg.burst_score_divisor)
    return Detection("frequency_burst", score, severity, level, tuple(reasons[: cfg.max_reasons]))


def _new_merchant(tx: Transaction, h: UserHistory, cfg: AnomalyConfig) -> Detection | None:
    if h.merchant_seen or not tx.merchant_key:
        return None
    amount = float(tx.amount)
    threshold = max(cfg.new_merchant_min_amount, h.expense_p95 or 0.0)
    if amount < threshold:
        return None
    level: HistoryLevel = "personal" if h.expense_count >= cfg.min_category_history else "limited"
    very_high = h.expense_p95 is not None and amount >= (
        cfg.new_merchant_p95_multiplier_high * h.expense_p95
    )
    severity = _cap("high" if very_high else "medium", level, cfg)
    reasons = [
        Reason(
            "NEW_MERCHANT",
            "merchant_seen",
            0.0,
            threshold,
            f"First time paying {tx.merchant_name}, and the amount is high for you",
        )
    ]
    if level == "limited":
        reasons.append(_limited_reason(cfg, h.expense_count))
    score = cfg.new_merchant_score_high if severity == "high" else cfg.new_merchant_score_medium
    return Detection(
        "new_merchant_high_value", score, severity, level, tuple(reasons[: cfg.max_reasons])
    )


def detect_surge(
    category_name: str,
    spend_last_window: float,
    weekly_spend: Sequence[float],
    cfg: AnomalyConfig,
    *,
    limited: bool = False,
) -> Detection | None:
    """Pattern anomaly (daily job): the last 7 days against the previous 8 weeks (7.6.2)."""
    if len(weekly_spend) < cfg.surge_baseline_weeks:
        return None
    if sum(1 for w in weekly_spend if w > 0) < cfg.surge_min_weeks_with_spend:
        return None
    norm = median(list(weekly_spend))
    if norm <= 0:
        return None
    if not (
        spend_last_window >= cfg.surge_min_ratio * norm
        and spend_last_window - norm >= cfg.surge_min_excess
    ):
        return None
    ratio = spend_last_window / norm
    level: HistoryLevel = "limited" if limited else "personal"
    severity = _cap("high" if ratio >= cfg.surge_high_ratio else "medium", level, cfg)
    return Detection(
        "category_surge",
        clip01(ratio / cfg.surge_score_divisor),
        severity,
        level,
        (
            Reason(
                "CATEGORY_SURGE",
                "cat_spend_7d_ratio",
                ratio,
                norm,
                f"{category_name} spending in the last 7 days is {ratio:.1f}× your weekly norm",
            ),
        ),
    )


def p95(values: Sequence[float]) -> float | None:
    return percentile(values, 0.95) if values else None
