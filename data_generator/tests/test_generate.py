import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from data_generator import GENERATOR_VERSION
from data_generator.generate import build_frames, write_dataset
from data_generator.tests.conftest import small_config
from ml.schemas.synthetic import (
    TRANSACTION_COLUMNS,
    validate_transactions,
)

CSV_IMPORT_COLUMNS = (
    "date",
    "description",
    "amount",
    "type",
    "payment_method",
    "merchant",
    "category",
    "notes",
)


def test_columns_start_with_product_csv_import_columns(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    assert tuple(tx.columns) == TRANSACTION_COLUMNS
    assert tuple(tx.columns[:8]) == CSV_IMPORT_COLUMNS


def test_every_user_has_transactions_and_one_user_row(frames, cfg) -> None:  # type: ignore[no-untyped-def]
    tx, users = frames
    assert len(users) == cfg.n_users
    assert set(tx["user_id"]) == set(users["user_id"])


def test_amounts_are_positive_two_dp_decimals(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    assert all(isinstance(a, Decimal) for a in tx["amount"])
    assert (tx["amount"] > Decimal(0)).all()


def test_dates_inside_simulation_window(frames, cfg) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    days = pd.to_datetime(tx["date"].str[:10])
    end = date(cfg.start_date.year, cfg.start_date.month + cfg.months, 1)
    assert days.min().date() >= cfg.start_date
    # frequency bursts may spill into the following day
    assert days.max().date() <= end + timedelta(days=1)


def test_transfers_use_transfer_category_only(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    transfers = tx[tx["type"] == "transfer"]
    assert len(transfers) > 0
    assert (transfers["true_category"] == "transfer").all()
    assert not (tx[tx["type"] != "transfer"]["true_category"] == "transfer").any()


def test_category_column_left_blank_for_the_classifier(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    assert tx["category"].isna().all()


def test_has_time_false_share_near_15_percent(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    assert 0.12 <= (~tx["has_time"]).mean() <= 0.18


def test_anomaly_share_and_types(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    expense = tx[tx["type"] == "expense"]
    share = expense["is_anomaly"].mean()
    assert 0.004 <= share <= 0.02
    assert set(expense[expense["is_anomaly"]]["anomaly_type"]) <= {
        "amount_spike",
        "frequency_burst",
        "new_merchant_high_value",
        "category_surge",
    }
    assert not tx[tx["type"] != "expense"]["is_anomaly"].any()


def test_fr_02_12_generator_injects_exact_duplicates(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    key = ["user_id", "date", "description", "amount", "type"]
    duplicated = tx.duplicated(key, keep=False)
    assert duplicated.sum() >= 2
    assert tx.duplicated(key).mean() < 0.01  # 0.3% injected plus rare natural collisions


def test_subscriptions_recur_roughly_monthly(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    recurring = tx[tx["recurring_series_id"].notna() & ~tx["is_anomaly"]].copy()
    assert len(recurring) > 0
    recurring["day"] = pd.to_datetime(recurring["date"].str[:10])
    for _, group in recurring.groupby("recurring_series_id"):
        days = group["day"].drop_duplicates().sort_values()
        gaps = days.diff().dropna().dt.days
        assert ((gaps >= 24) & (gaps <= 36)).all(), gaps.tolist()


def test_salary_never_lands_on_a_weekend(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    salary = tx[tx["true_category"] == "salary"]
    assert len(salary) > 0
    assert (pd.to_datetime(salary["date"].str[:10]).dt.day_of_week < 5).all()


def test_pandera_rejects_non_positive_amount(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    bad = tx.copy()
    bad.loc[0, "amount"] = Decimal("0.00")
    with pytest.raises(SchemaErrors):
        validate_transactions(bad)


def test_pandera_rejects_type_category_mismatch(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    bad = tx.copy()
    idx = bad.index[bad["type"] == "expense"][0]
    bad.loc[idx, "true_category"] = "salary"
    with pytest.raises(SchemaErrors):
        validate_transactions(bad)


def test_pandera_rejects_inconsistent_anomaly_columns(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    bad = tx.copy()
    idx = bad.index[~bad["is_anomaly"]][0]
    bad.loc[idx, "is_anomaly"] = True  # flagged but no anomaly_type
    with pytest.raises(SchemaErrors):
        validate_transactions(bad)


# ---- determinism and manifest ----------------------------------------------------------


def _hashes(directory: Path) -> dict[str, str]:
    manifest = json.loads((directory / "manifest.json").read_text())
    return manifest["files_sha256"]


def test_same_seed_is_byte_identical(tmp_path: Path) -> None:
    cfg = small_config(n_users=30, months=3)
    first = write_dataset(cfg, tmp_path / "a")
    second = write_dataset(small_config(n_users=30, months=3), tmp_path / "b")
    assert first["files_sha256"] == second["files_sha256"]
    for name in ("transactions.csv", "transactions.parquet", "users.parquet"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_worker_count_does_not_change_output(tmp_path: Path) -> None:
    one = write_dataset(small_config(n_users=120, months=2), tmp_path / "one", workers=1)
    two = write_dataset(small_config(n_users=120, months=2), tmp_path / "two", workers=2)
    assert one["files_sha256"] == two["files_sha256"]


def test_different_seed_changes_output(tmp_path: Path) -> None:
    a = write_dataset(small_config(seed=1, n_users=20, months=2), tmp_path / "a")
    b = write_dataset(small_config(seed=2, n_users=20, months=2), tmp_path / "b")
    assert a["files_sha256"]["transactions.csv"] != b["files_sha256"]["transactions.csv"]


def test_manifest_contents(tmp_path: Path) -> None:
    cfg = small_config(n_users=20, months=2)
    manifest = write_dataset(cfg, tmp_path)
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == json.loads(json.dumps(manifest))
    assert on_disk["generator_version"] == GENERATOR_VERSION
    assert on_disk["taxonomy_version"] == "taxonomy-1"
    assert on_disk["seed"] == 7
    assert on_disk["config"]["params"]["n_users"] == 20  # CLI overrides are inlined
    assert on_disk["row_counts"]["users"] == 20
    assert set(on_disk["files_sha256"]) == {
        "transactions.csv",
        "transactions.parquet",
        "users.parquet",
    }
    assert set(on_disk["config"]["input_files_sha256"]) >= {"default.yaml", "merchants.yaml"}
    assert "commit" in on_disk["git"]


def test_parquet_round_trips_decimal_amounts(tmp_path: Path) -> None:
    write_dataset(small_config(n_users=10, months=2), tmp_path)
    back = pd.read_parquet(tmp_path / "transactions.parquet")
    assert all(isinstance(a, Decimal) for a in back["amount"])
    csv = pd.read_csv(tmp_path / "transactions.csv", dtype=str)
    assert len(csv) == len(back)


def test_build_frames_validates_its_own_output() -> None:
    tx, users = build_frames(small_config(n_users=10, months=2))
    validate_transactions(tx)
    assert len(users) == 10


def test_true_merchant_is_always_present_and_clean(frames) -> None:  # type: ignore[no-untyped-def]
    tx, _ = frames
    assert tx["true_merchant"].notna().all()
    provided = tx[tx["merchant"].notna()]
    assert (provided["merchant"] == provided["true_merchant"]).all()
