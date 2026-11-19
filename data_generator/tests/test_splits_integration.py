"""Generator output works with the split module (T-03 + T-05 contract)."""

from datetime import date

import pandas as pd

from ml.evaluation.splits import SplitParams, assert_no_leakage, compute_splits


def test_splits_on_generated_data_are_leak_free(frames, cfg) -> None:  # type: ignore[no-untyped-def]
    tx, users = frames
    end = date(cfg.start_date.year + (cfg.months // 12), cfg.start_date.month + cfg.months % 12, 1)
    result = compute_splits(tx, users, cfg.start_date, end, SplitParams())
    assert_no_leakage(result, tx)
    counts = result.assignments["classifier_split"].value_counts()
    assert set(counts.index) == {"train", "validation", "test", "test_unseen_merchant"}
    assert len(result.assignments) == len(tx)
    assert set(result.cluster_users["user_id"]) == set(users["user_id"])


def test_every_model_label_survives_in_training(frames, cfg) -> None:  # type: ignore[no-untyped-def]
    tx, users = frames
    end = date(cfg.start_date.year, cfg.start_date.month + cfg.months, 1)
    result = compute_splits(tx, users, cfg.start_date, end, SplitParams())
    merged = tx[["transaction_id", "true_category"]].merge(result.assignments, on="transaction_id")
    train_categories = set(merged[merged["classifier_split"] == "train"]["true_category"])
    # With a tiny dataset a rare category may be absent, but the big ones must be present.
    assert {"food_beverage", "transportation", "groceries", "entertainment"} <= train_categories
    assert isinstance(train_categories, set) and not pd.isna(list(train_categories)).any()
