"""Behavior clustering (PRD 7.13, 9.5, 11.2.4): features, model, artifact."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import yaml

from ml.clustering.config import load_clustering_config
from ml.clustering.features import (
    EXPENSE_CATEGORIES,
    MODEL_COLUMNS,
    RAW_COLUMNS,
    SHARE_COLUMNS,
    model_matrix,
    raw_features,
)
from ml.clustering.model import Clusterer, fit, percentile_in, traits
from ml.config import config_dir

CFG = load_clustering_config()


def rows() -> pd.DataFrame:
    base = pd.Timestamp("2026-10-01 10:00")
    data = [
        # (day offset, type, amount, category, recurring)
        (0, "expense", 20000, "food_beverage", False),  # Thursday, small
        (2, "expense", 100000, "shopping", False),  # Saturday: weekend
        (3, "expense", 80000, "housing", True),  # Sunday: weekend, recurring
        (7, "expense", 100000, "food_beverage", False),
        (5, "income", 1000000, "salary", False),
        (20, "income", 1000000, "salary", False),
        (35, "income", 1000000, "salary", False),
    ]
    return pd.DataFrame(
        [
            {
                "occurred_at": base + pd.Timedelta(days=d),
                "type": t,
                "amount_f": a,
                "category": c,
                "recurring": r,
            }
            for d, t, a, c, r in data
        ]
    )


def test_fr_13_02_features_follow_the_definitions_of_11_2_4() -> None:
    f = raw_features(rows(), days=62, n_periods=2, cfg=CFG)
    assert f is not None and list(f) == list(RAW_COLUMNS)
    assert f["avg_tx_amount"] == 75000.0  # (20k + 100k + 80k + 100k) / 4
    assert f["monthly_expense"] == 150000.0  # 300k over 2 periods
    assert f["tx_per_day"] == pytest.approx(4 / 62)
    assert f["category_share_food_beverage"] == pytest.approx(120000 / 300000)
    assert sum(f[c] for c in SHARE_COLUMNS) == pytest.approx(1.0)
    assert f["weekend_spend_ratio"] == pytest.approx(180000 / 300000)  # Saturday + Sunday
    assert f["recurring_ratio"] == pytest.approx(80000 / 300000)
    assert f["small_tx_ratio"] == 0.25  # only the Rp20.000 one is below Rp25.000
    assert f["income_regularity"] == pytest.approx(0.0)  # incomes exactly 15 and 15 days apart
    assert f["savings_rate"] == pytest.approx((3000000 - 300000) / 3000000)


def test_fr_13_02_missing_income_is_nan_and_no_expense_means_no_features() -> None:
    expense_only = rows()[lambda d: d["type"] == "expense"]
    f = raw_features(expense_only, days=62, n_periods=2, cfg=CFG)
    assert f is not None and np.isnan(f["income_regularity"]) and np.isnan(f["savings_rate"])
    assert raw_features(rows()[lambda d: d["type"] == "income"], 62, 2, CFG) is None
    assert raw_features(rows(), days=0, n_periods=2, cfg=CFG) is None


def test_fr_13_02_category_shares_are_centred_log_ratios() -> None:
    f = raw_features(rows(), days=62, n_periods=2, cfg=CFG)
    assert f is not None
    m = model_matrix(pd.DataFrame([f]), CFG)
    assert list(m.columns) == list(MODEL_COLUMNS)
    clr = m[[f"clr_{c}" for c in EXPENSE_CATEGORIES]].to_numpy()
    assert clr.sum() == pytest.approx(0.0, abs=1e-9)  # CLR rows sum to zero (FR-13.02)
    assert m["log_monthly_expense"].iloc[0] == pytest.approx(np.log1p(150000.0))


def test_fr_13_01_features_ignore_rows_outside_what_the_caller_passes() -> None:
    f1 = raw_features(rows(), 62, 2, CFG)
    extra = pd.concat([rows(), rows().assign(amount_f=1e9)], ignore_index=True)
    f2 = raw_features(extra, 62, 2, CFG)
    assert f1 != f2  # the function uses exactly the rows it is given: windowing is the caller's job


def blobs() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    out = []
    for centre, n in ((0.1, 60), (0.6, 60)):
        for _ in range(n):
            shares = rng.dirichlet(np.ones(len(SHARE_COLUMNS)) * 3)
            row = dict.fromkeys(RAW_COLUMNS, 0.0)
            row.update(zip(SHARE_COLUMNS, shares, strict=True))
            row.update(
                avg_tx_amount=50000 * (1 + centre * 10) + rng.normal(0, 500),
                monthly_expense=2e6 * (1 + centre * 10) + rng.normal(0, 5e4),
                tx_per_day=1 + centre * 5 + rng.normal(0, 0.05),
                weekend_spend_ratio=centre,
                recurring_ratio=0.2,
                small_tx_ratio=1 - centre,
                income_regularity=0.1,
                savings_rate=centre - 0.3,
            )
            out.append(row)
    return pd.DataFrame(out)[list(RAW_COLUMNS)]


def test_fr_13_01_fit_assign_is_deterministic_and_separates_two_groups() -> None:
    raw = blobs()
    a, b = fit(raw, 2, CFG, "t"), fit(raw, 2, CFG, "t")
    assert a.centroids == b.centroids
    labels, dist = a.assign(raw, CFG)
    assert len(set(labels[:60])) == 1 and len(set(labels[60:])) == 1 and labels[0] != labels[60]
    assert (dist >= 0).all() and sorted(s.size for s in a.segments) == [60, 60]


def test_fr_13_03_artifact_roundtrip_keeps_names_and_assignment() -> None:
    raw = blobs()
    model = fit(raw, 2, CFG, "t")
    model.segments[0].name, model.segments[0].description = "Name A", "Desc A"
    again = Clusterer.from_dict(yaml.safe_load(yaml.safe_dump(model.to_dict())))
    assert again.segments[0].name == "Name A"
    assert again.assign(raw, CFG)[0].tolist() == model.assign(raw, CFG)[0].tolist()


def test_fr_13_04_percentile_and_traits_pick_what_stands_out() -> None:
    deciles = [float(v) for v in range(0, 101, 10)]  # uniform 0..100
    assert percentile_in(70.0, deciles) == pytest.approx(70.0)
    assert percentile_in(-5.0, deciles) == 0.0 and percentile_in(500.0, deciles) == 100.0
    assert 0.0 < percentile_in(0.0, [0.0] * 11) <= 100.0  # flat deciles do not divide by zero

    from ml.clustering.model import Segment

    seg = Segment(
        "s", deciles={"savings_rate": deciles, "tx_per_day": deciles, "small_tx_ratio": deciles}
    )
    found = traits({"savings_rate": 95.0, "tx_per_day": 52.0, "small_tx_ratio": 10.0}, seg, CFG)
    assert [(t["feature"], t["direction"], t["percent"]) for t in found] == [
        ("savings_rate", "higher", 95),
        ("small_tx_ratio", "lower", 90),
    ]  # tx_per_day sits in the middle: not a trait
    assert traits({"savings_rate": float("nan")}, seg, CFG) == []


def test_fr_13_03_committed_artifact_is_complete_and_named() -> None:
    data = yaml.safe_load((config_dir() / "clusterer_model.yaml").read_text(encoding="utf-8"))
    model = Clusterer.from_dict(data)
    assert model.version == load_clustering_config().version
    assert len(model.centroids) == len(model.segments) >= 3
    assert all(len(c) == len(MODEL_COLUMNS) for c in model.centroids)
    assert all(s.name and s.description for s in model.segments)  # FR-13.03: nameable
    assert all(set(s.deciles) <= set(RAW_COLUMNS) and s.size > 0 for s in model.segments)
