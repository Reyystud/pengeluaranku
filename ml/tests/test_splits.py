"""Tests for the locked evaluation splits (PRD 10.4). Frames are hand-built, no randomness."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ml.evaluation.splits import (
    SplitParams,
    assert_no_leakage,
    complete_periods,
    compute_splits,
    forecast_origins,
    verify_split_files,
    write_split_files,
)

WINDOW = (date(2025, 1, 1), date(2026, 1, 1))
CATEGORIES = ("food_beverage", "groceries", "transportation", "entertainment")


def build(rows_per_user: dict[str, int], start_day: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deterministic ledger: row i of user u -> category i%4, merchant from an 8-name pool."""
    records = []
    for u_index, (user, n) in enumerate(rows_per_user.items()):
        for i in range(n):
            day = date.fromordinal(WINDOW[0].toordinal() + (i * 360) // max(n, 1))
            category = CATEGORIES[i % 4]
            merchant = f"{category}-m{(i * 3 + u_index) % 8}"
            when = f"{day.isoformat()} {8 + i % 12:02d}:00" if i % 5 else day.isoformat()
            records.append((f"{user}-{i:04d}", user, when, merchant, category))
    tx = pd.DataFrame(
        records, columns=["transaction_id", "user_id", "date", "true_merchant", "true_category"]
    )
    users = pd.DataFrame(
        {
            "user_id": list(rows_per_user),
            "archetype": [
                "student" if i % 2 == 0 else "freelancer" for i in range(len(rows_per_user))
            ],
            "budget_period_start_day": start_day,
        }
    )
    return tx, users


NO_HOLDOUT = SplitParams(merchant_holdout_pct=0)


def test_temporal_cut_points_70_15_15() -> None:
    tx, users = build({"u1": 20, "u2": 10})
    result = compute_splits(tx, users, *WINDOW, NO_HOLDOUT)
    a = result.assignments
    for user, expected in (("u1", (14, 3, 3)), ("u2", (7, 1, 2))):
        labels = a[a["user_id"] == user]["classifier_split"].value_counts()
        got = (
            int(labels.get("train", 0)),
            int(labels.get("validation", 0)),
            int(labels.get("test", 0)),
        )
        assert got == expected


def test_cuts_are_chronological_and_leak_free() -> None:
    tx, users = build({f"u{i}": 40 + i for i in range(6)})
    result = compute_splits(tx, users, *WINDOW)
    assert_no_leakage(result, tx)


def test_date_only_rows_sort_at_noon() -> None:
    from ml.evaluation.splits import _sort_key

    keys = _sort_key(pd.Series(["2025-03-05", "2025-03-05 09:00", "2025-03-05 15:00"]))
    assert list(keys) == ["2025-03-05 12:00", "2025-03-05 09:00", "2025-03-05 15:00"]
    assert sorted(keys) == ["2025-03-05 09:00", "2025-03-05 12:00", "2025-03-05 15:00"]


def test_result_is_independent_of_row_order() -> None:
    tx, users = build({f"u{i}": 30 for i in range(8)})
    shuffled_tx = tx.sample(frac=1.0, random_state=0).reset_index(drop=True)
    shuffled_users = users.sample(frac=1.0, random_state=1).reset_index(drop=True)
    a = compute_splits(tx, users, *WINDOW).hashes()
    b = compute_splits(shuffled_tx, shuffled_users, *WINDOW).hashes()
    assert a == b


def test_heldout_merchants_have_all_rows_in_unseen_split_and_nowhere_else() -> None:
    tx, users = build({f"u{i}": 80 for i in range(10)})
    result = compute_splits(tx, users, *WINDOW)
    heldout = set(result.heldout_merchants["merchant"])
    merged = tx.merge(result.assignments, on="transaction_id")
    in_unseen = merged["classifier_split"] == "test_unseen_merchant"
    assert in_unseen.sum() > 0
    assert set(merged[in_unseen]["true_merchant"]) == heldout
    assert not merged[~in_unseen]["true_merchant"].isin(heldout).any()


def test_every_category_keeps_a_merchant_outside_the_holdout() -> None:
    tx, users = build({f"u{i}": 200 for i in range(8)})
    result = compute_splits(tx, users, *WINDOW)
    heldout = set(result.heldout_merchants["merchant"])
    for category in CATEGORIES:
        all_merchants = set(tx[tx["true_category"] == category]["true_merchant"])
        assert all_merchants - heldout, category
        assert all_merchants & heldout, category  # >= 1 held out per category


def test_holdout_fraction_close_to_15_percent_of_a_large_category() -> None:
    names = [f"merchant-{i:03d}" for i in range(40)]
    tx = pd.DataFrame(
        {
            "transaction_id": [f"t{i}" for i in range(40)],
            "user_id": "u1",
            "date": "2025-02-01",
            "true_merchant": names,
            "true_category": "shopping",
        }
    )
    users = pd.DataFrame(
        {"user_id": ["u1"], "archetype": ["student"], "budget_period_start_day": 1}
    )
    result = compute_splits(tx, users, *WINDOW)
    assert len(result.heldout_merchants) == 6  # round(0.15 * 40)


def test_seed_changes_the_holdout() -> None:
    tx, users = build({f"u{i}": 80 for i in range(6)})
    a = compute_splits(tx, users, *WINDOW, SplitParams(seed=1)).heldout_merchants
    b = compute_splits(tx, users, *WINDOW, SplitParams(seed=2)).heldout_merchants
    assert not a.equals(b)


def test_cluster_split_is_disjoint_complete_and_balanced_per_archetype() -> None:
    tx, users = build({f"u{i:02d}": 12 for i in range(11)})
    result = compute_splits(tx, users, *WINDOW)
    clusters = result.cluster_users
    assert sorted(clusters["user_id"]) == sorted(users["user_id"])
    assert clusters["user_id"].is_unique
    counts = clusters.groupby(["archetype", "half"]).size().unstack(fill_value=0)
    assert ((counts["A"] - counts["B"]).abs() <= 1).all()


def test_complete_periods_start_day_25_across_year_end() -> None:
    periods = complete_periods(25, *WINDOW, last_n=4)
    assert [p[0].isoformat() for p in periods] == [
        "2025-08-25",
        "2025-09-25",
        "2025-10-25",
        "2025-11-25",
    ]
    assert periods[-1][1] == date(2025, 12, 24)  # 2025-12-25.. is incomplete at window end


def test_complete_periods_start_day_1_includes_december() -> None:
    periods = complete_periods(1, *WINDOW, last_n=4)
    assert [p[0].isoformat() for p in periods] == [
        "2025-09-01",
        "2025-10-01",
        "2025-11-01",
        "2025-12-01",
    ]
    assert periods[-1][1] == date(2025, 12, 31)


def test_complete_periods_excludes_periods_starting_before_window() -> None:
    periods = complete_periods(25, date(2025, 1, 1), date(2025, 3, 1), last_n=10)
    assert [p[0].isoformat() for p in periods] == ["2025-01-25"]


def test_forecast_origins_are_day_k_of_each_period() -> None:
    tx, users = build({"u1": 50}, start_day=25)
    params = SplitParams()
    result = compute_splits(tx, users, *WINDOW, params)
    origins = forecast_origins(result.forecast_periods, params)
    assert len(origins) == 4 * 4
    first = origins[origins["period_start"] == "2025-11-25"]
    assert list(first["origin_day"]) == [5, 10, 15, 20]
    assert list(first["origin_date"]) == ["2025-11-29", "2025-12-04", "2025-12-09", "2025-12-14"]
    assert (origins["origin_date"] <= origins["period_end"]).all()


# ---- persistence and locking --------------------------------------------------------------


def test_write_and_verify_round_trip(tmp_path: Path) -> None:
    tx, users = build({f"u{i}": 40 for i in range(5)})
    result = compute_splits(tx, users, *WINDOW)
    summary = write_split_files(result, tmp_path, {"dataset_version": "test/v1"}, tmp_path / "ids")
    assert verify_split_files(result, tmp_path) == []
    assert summary["counts"]["transactions"] == len(tx)
    assert (tmp_path / "ids" / "assignments.parquet").exists()
    on_disk = json.loads((tmp_path / "splits.json").read_text())
    assert on_disk["hashes"]["split_hash"] == result.hashes()["split_hash"]


def test_verify_detects_a_changed_split(tmp_path: Path) -> None:
    tx, users = build({f"u{i}": 40 for i in range(5)})
    write_split_files(compute_splits(tx, users, *WINDOW), tmp_path, {})
    changed = compute_splits(tx, users, *WINDOW, SplitParams(train_pct=60))
    problems = verify_split_files(changed, tmp_path)
    assert any("split_hash" in p for p in problems)
    assert any("params" in p for p in problems)


def test_missing_columns_are_rejected() -> None:
    tx, users = build({"u1": 10})
    with pytest.raises(ValueError, match="missing columns"):
        compute_splits(tx.drop(columns=["true_merchant"]), users, *WINDOW)


def test_golden_split_hash_for_algorithm_lock() -> None:
    """Changing the split algorithm changes this hash; that requires an ADR (PRD 10.4)."""
    tx, users = build({f"u{i}": 60 for i in range(6)})
    assert compute_splits(tx, users, *WINDOW).hashes()["split_hash"] == GOLDEN_SPLIT_HASH


GOLDEN_SPLIT_HASH = "1db159f8339b60f5f47daab9e521c0b8e7a6fbaac50386d11effe4eb60f48871"
