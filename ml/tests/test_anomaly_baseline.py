"""Baseline anomaly detector (PRD 7.6.2 - 7.6.5): formulas, cold start, reasons, leakage."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ml.anomaly_detection import (
    CategoryPrior,
    Transaction,
    UserHistory,
    detect,
    detect_surge,
    load_anomaly_config,
)
from ml.anomaly_detection.baseline import idr
from ml.anomaly_detection.config import load_category_priors
from ml.anomaly_detection.history import build_history
from ml.anomaly_detection.stats import (
    clip01,
    mad,
    median,
    modified_z,
    percent_rank,
    percentile,
    poisson_sf,
)
from ml.features.testing import assert_point_in_time
from ml.taxonomy import MODEL_LABELS

CFG = load_anomaly_config()
FOOD = "Food & Beverage"


def tx(amount: str, key: str = "kopi", name: str = "Kopi") -> Transaction:
    return Transaction(Decimal(amount), FOOD, key, name)


def regular_history(n: int = 40, base: float = 40000.0, **over: Any) -> UserHistory:
    """A steady spender: amounts within +-10% of ``base``."""
    amounts = [base * (1 + ((i % 5) - 2) * 0.05) for i in range(n)]
    fields: dict[str, Any] = {"merchant_seen": True, "expense_count": n} | over
    return UserHistory(category_amounts=amounts, **fields)


# --- statistics -----------------------------------------------------------------------------------
def test_fr_06_median_mad_and_modified_z_match_the_definition() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    assert median(values) == 3.0
    assert mad(values) == 1.0  # |v - 3| = 2, 1, 0, 1, 97 -> median 1
    assert modified_z(5.0, 3.0, 1.0, 0.05, 0.6745) == pytest.approx(0.6745 * 2.0)
    assert modified_z(5.0, 3.0, 0.0, 0.05, 0.6745) == pytest.approx(0.6745 * 2.0 / 0.05)  # floor


def test_fr_06_02_score_mapping_matches_the_prd_anchors() -> None:
    """z = 3.5 -> 0.25, z = 5 -> 0.5, z = 8 -> 1.0 (7.6.2)."""
    s = CFG
    for z, score in ((3.5, 0.25), (5.0, 0.5), (8.0, 1.0), (20.0, 1.0), (1.0, 0.0)):
        assert clip01((z - s.spike_score_offset) / s.spike_score_divisor) == pytest.approx(score)


def test_fr_06_poisson_tail_matches_the_exact_sum() -> None:
    for k, lam in ((3, 0.1), (5, 1.0), (6, 1.0), (10, 2.5), (1, 0.7)):
        exact = 1.0 - sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k))
        assert poisson_sf(k, lam) == pytest.approx(max(exact, 0.0), rel=1e-9, abs=1e-12)
    assert poisson_sf(0, 1.0) == 1.0
    scipy_stats = pytest.importorskip("scipy.stats")
    assert poisson_sf(7, 0.4) == pytest.approx(scipy_stats.poisson.sf(6, 0.4), rel=1e-9)


def test_fr_06_percentile_and_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(values, 0.95) == pytest.approx(48.0)  # percentile_cont(0.95)
    assert percentile(values, 0.5) == 30.0
    assert percent_rank(35.0, values) == 60.0
    assert percent_rank(5.0, []) == 0.0


# --- amount spike ---------------------------------------------------------------------------------
def test_fr_06_02_a_large_amount_is_a_high_severity_spike_with_reasons() -> None:
    (d,) = [
        x for x in detect(tx("400000"), regular_history(), CFG) if x.anomaly_type == "amount_spike"
    ]
    assert d.severity == "high" and d.history_level == "personal" and d.z is not None and d.z >= 5
    assert 0.5 <= d.score <= 1.0
    codes = [r.code for r in d.reasons]
    assert codes[0] == "AMOUNT_VS_CATEGORY" and "AMOUNT_PERCENTILE" in codes and len(codes) <= 3
    first = d.reasons[0]
    assert first.message.startswith("9.") or first.message.startswith("10.")  # ratio of ~10x
    assert "Rp4" in first.message and "Food & Beverage" in first.message


@pytest.mark.parametrize(
    ("amount", "why"),
    [
        ("45000", "close to typical"),
        ("79000", "under twice the typical amount"),
        ("48000", "under MIN_ALERT_AMOUNT"),
    ],
)
def test_fr_06_02_normal_and_small_amounts_are_not_flagged(amount: str, why: str) -> None:
    assert [
        d for d in detect(tx(amount), regular_history(), CFG) if d.anomaly_type == "amount_spike"
    ] == [], why


def test_fr_06_02_all_three_conditions_are_required() -> None:
    # Typical Rp5.000: Rp40.000 is far above typical (z large, 8x) but below MIN_ALERT_AMOUNT.
    h = regular_history(base=5000.0)
    assert not [d for d in detect(tx("40000"), h, CFG) if d.anomaly_type == "amount_spike"]
    assert [d for d in detect(tx("60000"), h, CFG) if d.anomaly_type == "amount_spike"]


def test_fr_06_mad_floor_keeps_a_perfectly_regular_spender_from_dividing_by_zero() -> None:
    h = UserHistory(category_amounts=[40000.0] * 40, merchant_seen=True, expense_count=40)
    spike = [d for d in detect(tx("200000"), h, CFG) if d.anomaly_type == "amount_spike"]
    assert spike and math.isfinite(spike[0].z or math.nan)
    assert not [d for d in detect(tx("40000"), h, CFG) if d.anomaly_type == "amount_spike"]


def test_fr_06_06_unusually_low_amounts_are_low_severity_and_never_alert_types() -> None:
    h = regular_history(base=400000.0)
    low = [d for d in detect(tx("1000"), h, CFG) if d.anomaly_type == "amount_low"]
    assert low and low[0].severity == "low"


def test_fr_06_ratio_to_the_merchant_adds_a_reason_when_the_merchant_is_known() -> None:
    h = regular_history(merchant_amounts=[40000.0, 41000.0, 39000.0, 40000.0])
    (d,) = [x for x in detect(tx("400000"), h, CFG) if x.anomaly_type == "amount_spike"]
    assert [r.code for r in d.reasons] == [
        "AMOUNT_VS_CATEGORY",
        "AMOUNT_PERCENTILE",
        "AMOUNT_VS_MERCHANT",
    ]


# --- cold start (7.6.4) ---------------------------------------------------------------------------
def test_fr_06_cold_start_uses_the_category_prior_and_caps_severity() -> None:
    prior = CategoryPrior(median=math.log1p(40000), mad=0.5)
    short = UserHistory(category_amounts=[40000.0] * 10, expense_count=10, prior=prior)
    (d,) = [x for x in detect(tx("4000000"), short, CFG) if x.anomaly_type == "amount_spike"]
    assert d.history_level == "limited" and d.severity == "medium"  # would be high with history
    assert d.reasons[-1].code == "LIMITED_HISTORY"
    assert d.reasons[-1].message == (
        "Based on typical spending for this category (limited personal history)"
    )
    assert "AMOUNT_PERCENTILE" not in [r.code for r in d.reasons]  # no personal percentile


def test_fr_06_cold_start_without_a_prior_says_nothing() -> None:
    short = UserHistory(category_amounts=[40000.0] * 5, expense_count=5)
    assert not [d for d in detect(tx("4000000"), short, CFG) if d.anomaly_type == "amount_spike"]


def test_fr_06_thirty_prior_transactions_in_the_category_switch_to_personal() -> None:
    prior = CategoryPrior(median=math.log1p(1000), mad=0.5)  # a misleading prior
    at_29 = regular_history(29, prior=prior)
    at_30 = regular_history(30, prior=prior)
    assert detect(tx("60000"), at_29, CFG)[0].history_level == "limited"
    assert not [d for d in detect(tx("60000"), at_30, CFG) if d.anomaly_type == "amount_spike"]


# --- frequency burst ------------------------------------------------------------------------------
def test_fr_06_02_burst_needs_three_in_24h_and_a_small_poisson_tail() -> None:
    quiet = regular_history(category_count_rate_window=10)  # ~0.18/day
    assert not [
        d for d in detect(tx("20000"), quiet, CFG) if d.anomaly_type == "frequency_burst"
    ]  # k = 1
    two = regular_history(category_count_24h=1, category_count_rate_window=10)
    assert not [d for d in detect(tx("20000"), two, CFG) if d.anomaly_type == "frequency_burst"]
    four = regular_history(category_count_24h=3, category_count_rate_window=10)
    (b,) = [d for d in detect(tx("20000"), four, CFG) if d.anomaly_type == "frequency_burst"]
    lam = 10 / 56
    p = poisson_sf(4, lam)
    assert p < 0.001
    assert b.score == pytest.approx(clip01(-math.log10(p) / 6))
    assert b.severity == ("high" if p < 1e-5 else "medium")
    assert b.reasons[0].code == "FREQUENCY_BURST"
    assert b.reasons[0].message.startswith("4 Food & Beverage transactions in 24 hours")


def test_fr_06_burst_is_not_flagged_for_someone_who_always_buys_often() -> None:
    busy = regular_history(category_count_24h=4, category_count_rate_window=56 * 4)  # 4 a day
    assert not [d for d in detect(tx("20000"), busy, CFG) if d.anomaly_type == "frequency_burst"]


def test_fr_06_burst_rate_has_a_floor() -> None:
    nothing = regular_history(category_count_24h=2, category_count_rate_window=0)
    (b,) = [d for d in detect(tx("20000"), nothing, CFG) if d.anomaly_type == "frequency_burst"]
    assert b.reasons[0].reference == CFG.burst_min_rate  # lambda = 0.1


def test_fr_06_burst_high_when_the_tail_is_tiny() -> None:
    h = regular_history(category_count_24h=7, category_count_rate_window=0)
    (b,) = [d for d in detect(tx("20000"), h, CFG) if d.anomaly_type == "frequency_burst"]
    assert poisson_sf(8, 0.1) < 1e-5 and b.severity == "high"


# --- new merchant ---------------------------------------------------------------------------------
def test_fr_06_02_new_merchant_needs_a_high_amount_for_this_user() -> None:
    h = regular_history(expense_p95=800000.0, merchant_seen=False)
    assert not [
        d
        for d in detect(tx("700000", "new", "New"), h, CFG)
        if d.anomaly_type == "new_merchant_high_value"
    ]
    (d,) = [
        x
        for x in detect(tx("900000", "new", "New"), h, CFG)
        if x.anomaly_type == "new_merchant_high_value"
    ]
    assert (d.severity, d.score) == ("medium", 0.6)
    (very,) = [
        x
        for x in detect(tx("2500000", "new", "New"), h, CFG)
        if x.anomaly_type == "new_merchant_high_value"
    ]
    assert (very.severity, very.score) == ("high", 0.9)  # >= 3 x P95
    assert very.reasons[0].code == "NEW_MERCHANT"


def test_fr_06_new_merchant_floor_is_the_config_value_when_p95_is_lower() -> None:
    h = regular_history(expense_p95=60000.0, merchant_seen=False)
    assert not [
        d
        for d in detect(tx("400000", "n", "N"), h, CFG)
        if d.anomaly_type == "new_merchant_high_value"
    ]
    assert [
        d
        for d in detect(tx("500000", "n", "N"), h, CFG)
        if d.anomaly_type == "new_merchant_high_value"
    ]


def test_fr_06_a_known_or_empty_merchant_is_never_new() -> None:
    seen = regular_history(expense_p95=100000.0, merchant_seen=True)
    assert not [
        d for d in detect(tx("9000000"), seen, CFG) if d.anomaly_type == "new_merchant_high_value"
    ]
    blank = regular_history(expense_p95=100000.0, merchant_seen=False)
    assert not [
        d
        for d in detect(tx("9000000", "", ""), blank, CFG)
        if d.anomaly_type == "new_merchant_high_value"
    ]


def test_fr_06_new_merchant_with_a_short_history_is_limited_and_medium() -> None:
    h = UserHistory(expense_count=5, merchant_seen=False, expense_p95=100000.0)
    (d,) = [
        x
        for x in detect(tx("9000000", "n", "N"), h, CFG)
        if x.anomaly_type == "new_merchant_high_value"
    ]
    assert (d.history_level, d.severity) == ("limited", "medium")
    assert d.reasons[-1].code == "LIMITED_HISTORY"


# --- category surge -------------------------------------------------------------------------------
def test_fr_06_02_surge_needs_ratio_excess_and_enough_weeks_with_spend() -> None:
    weeks = [300000.0, 250000.0, 400000.0, 350000.0, 300000.0, 320000.0, 280000.0, 310000.0]
    d = detect_surge(FOOD, 900000.0, weeks, CFG)
    assert d is not None and d.anomaly_type == "category_surge" and d.severity == "medium"
    assert d.reasons[0].code == "CATEGORY_SURGE" and "weekly norm" in d.reasons[0].message
    high = detect_surge(FOOD, 1400000.0, weeks, CFG)
    assert high is not None and high.severity == "high"
    assert detect_surge(FOOD, 500000.0, weeks, CFG) is None  # ratio below 2
    small = [50000.0] * 8
    assert detect_surge(FOOD, 110000.0, small, CFG) is None  # ratio 2.2 but excess < Rp200.000
    sparse = [0.0, 0.0, 0.0, 0.0, 0.0, 300000.0, 300000.0, 300000.0]  # only 3 weeks with spend
    assert detect_surge(FOOD, 5000000.0, sparse, CFG) is None
    assert detect_surge(FOOD, 5000000.0, weeks[:5], CFG) is None  # fewer than 8 weeks of data


def test_fr_06_surge_score_follows_the_ratio() -> None:
    weeks = [100000.0] * 8
    d = detect_surge(FOOD, 400000.0, weeks, CFG)
    assert d is not None and d.score == pytest.approx(0.5)  # ratio 4 / 8


# --- formatting and config ------------------------------------------------------------------------
def test_fr_06_idr_formatting() -> None:
    assert idr(45000) == "Rp45.000" and idr(1234567.4) == "Rp1.234.567" and idr(0) == "Rp0"


def test_fr_06_thresholds_come_from_the_versioned_config() -> None:
    assert CFG.version == "baseline-1" and CFG.feature_version == "anomaly-features-1"
    assert (CFG.z_threshold, CFG.mad_floor, CFG.min_alert_amount) == (3.5, 0.05, 50000.0)
    assert (CFG.alerts_per_period, CFG.min_category_history, CFG.min_history_days) == (3, 30, 7)
    assert CFG.suppression_days == 90 and CFG.alert_max_age_days == 7


def test_fr_06_priors_cover_known_categories_only() -> None:
    priors = load_category_priors()
    assert priors, "run python -m ml.anomaly_detection.priors"
    assert set(priors) <= set(MODEL_LABELS)
    assert all(mad_value > 0 for _, mad_value in priors.values())


# --- properties -----------------------------------------------------------------------------------
@settings(max_examples=150, deadline=None)
@given(
    amount=st.integers(1_000, 50_000_000),
    base=st.integers(5_000, 500_000),
    n=st.integers(0, 80),
    k24=st.integers(0, 12),
    rate=st.integers(0, 400),
    seen=st.booleans(),
)
def test_fr_06_03_every_detection_is_well_formed(
    amount: int, base: int, n: int, k24: int, rate: int, seen: bool
) -> None:
    prior = CategoryPrior(math.log1p(base), 0.5)
    h = UserHistory(
        category_amounts=[float(base)] * n,
        merchant_seen=seen,
        expense_p95=float(base) * 3,
        expense_count=n,
        category_count_24h=k24,
        category_count_rate_window=rate,
        prior=prior,
    )
    for d in detect(tx(str(amount)), h, CFG):
        assert 0.0 <= d.score <= 1.0
        assert d.severity in ("low", "medium", "high")
        assert 1 <= len(d.reasons) <= CFG.max_reasons
        assert all(
            r.message and math.isfinite(r.value) and math.isfinite(r.reference) for r in d.reasons
        )
        if d.history_level == "limited":
            assert d.severity != "high"  # 7.6.4: capped at medium
            assert d.reasons[-1].code == "LIMITED_HISTORY" or len(d.reasons) == CFG.max_reasons
        if d.anomaly_type == "amount_spike":
            assert d.z is not None and d.z >= CFG.z_threshold
            assert (d.severity == "high") == (
                d.z >= CFG.spike_high_z
            ) or d.history_level == "limited"


@settings(max_examples=100, deadline=None)
@given(a=st.integers(60_000, 5_000_000), b=st.integers(60_000, 5_000_000))
def test_fr_06_a_larger_amount_never_scores_lower(a: int, b: int) -> None:
    lo, hi = sorted((a, b))
    h = regular_history(60)

    def score(amount: int) -> float:
        found = [d for d in detect(tx(str(amount)), h, CFG) if d.anomaly_type == "amount_spike"]
        return found[0].score if found else -1.0

    assert score(lo) <= score(hi)


# --- point in time (11.1 rule 2) ------------------------------------------------------------------
def frame(n: int = 60) -> pd.DataFrame:
    start = datetime(2026, 1, 1, 9, tzinfo=UTC)
    rows = [
        {
            "occurred_at": start + timedelta(hours=7 * i),
            "created_at": i,
            "type": "expense" if i % 9 else "income",
            "amount": 30000.0 + (i % 7) * 4000.0,
            "category": "food_beverage" if i % 3 else "groceries",
            "merchant_key": f"m{i % 5}",
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows)


def test_fr_06_history_features_ignore_rows_at_or_after_the_transaction() -> None:
    history = frame()
    as_of = history["occurred_at"].iloc[40]

    def features(h: pd.DataFrame, when: datetime) -> UserHistory:
        return build_history(h, when, "food_beverage", "m1", CFG)

    assert_point_in_time(features, history, as_of.to_pydatetime())


def test_fr_06_history_builder_counts_windows_the_way_the_prd_defines_them() -> None:
    history = frame()
    as_of = history["occurred_at"].iloc[40].to_pydatetime()
    h = build_history(history, as_of, "food_beverage", "m1", CFG)
    seen = history[history["occurred_at"] < as_of]
    cat = seen[(seen["type"] == "expense") & (seen["category"] == "food_beverage")]
    assert len(h.category_amounts) == len(cat)
    assert h.category_count_24h == int((cat["occurred_at"] > as_of - timedelta(days=1)).sum())
    assert h.category_count_rate_window == len(cat)  # all within 56 days
    assert h.expense_count == int((seen["type"] == "expense").sum())
    assert h.merchant_seen is True
    assert build_history(history, as_of, "food_beverage", "never", CFG).merchant_seen is False
    assert build_history(history.iloc[0:0], as_of, "food_beverage", "m1", CFG).history_days == 0.0


def top_score(amount: str) -> float:
    found = detect(tx(amount), regular_history(), CFG)
    return max((d.score for d in found), default=0.0)


def test_fr_21_04_directional_five_times_the_amount_raises_the_score() -> None:
    """PRD 21.4: same features, amount x5 -> the score increases (it saturates at 1.0, so the
    strict check uses amounts whose unscaled version is not already saturated)."""
    for base in ("50000", "60000", "80000"):
        assert top_score(str(int(base) * 5)) > top_score(base)
    ladder = [top_score(a) for a in ("40000", "60000", "100000", "200000", "1000000")]
    assert ladder == sorted(ladder)  # never decreases as the amount grows
