"""Parity and point-in-time tests for features (PRD 11.1, 21.2; T-08)."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from ml.features import FEATURE_VERSION
from ml.features.classifier import (
    FEATURE_COLUMNS,
    TransactionInput,
    build_feature_frame,
    hour_bucket,
    online_features,
    row_to_input,
)
from ml.features.point_in_time import history_before
from ml.features.testing import assert_frames_parity, assert_point_in_time

DATA = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "v1" / "transactions.parquet"


def sample_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "description": [
                "GOPAY*Kopi Kenangan #12345",
                "INDOMARET - JKT SELATAN",
                "Gaji bulanan",
                "x",
            ],
            "merchant": [None, "Indomaret", None, None],
            "amount": [
                Decimal("25000.00"),
                Decimal("1500.50"),
                Decimal("7500000.00"),
                Decimal("1.00"),
            ],
            "type": ["expense", "expense", "income", "transfer"],
            "payment_method": ["e_wallet", "qris", "bank_transfer", "cash"],
            "date": ["2025-03-01 08:30", "2025-03-02", "2025-03-25 00:00", "2025-03-03 23:59"],
        }
    )


def online_frame(df: pd.DataFrame) -> pd.DataFrame:
    rows = [online_features(row_to_input(r)) for _, r in df.iterrows()]
    return pd.DataFrame(rows, index=df.index)[list(FEATURE_COLUMNS)]


def test_features_batch_online_parity() -> None:
    df = sample_rows()
    assert_frames_parity(build_feature_frame(df), online_frame(df))


@pytest.mark.skipif(not DATA.exists(), reason="needs data/synthetic/v1 (make data)")
def test_features_batch_online_parity_synthetic_sample() -> None:
    tx = pd.read_parquet(
        DATA, columns=list(("description", "merchant", "amount", "type", "payment_method", "date"))
    )
    sample = tx.sample(5000, random_state=7)
    assert_frames_parity(build_feature_frame(sample), online_frame(sample))


def test_parity_harness_detects_a_mismatch() -> None:
    df = sample_rows()
    batch = build_feature_frame(df)
    broken = batch.copy()
    broken.loc[0, "hour_bucket"] = "night"
    with pytest.raises(AssertionError, match="hour_bucket"):
        assert_frames_parity(batch, broken)
    broken = batch.copy()
    broken.loc[1, "log_amount"] += 1e-3
    with pytest.raises(AssertionError, match="log_amount"):
        assert_frames_parity(batch, broken)


@pytest.mark.parametrize(
    ("hour", "bucket"),
    [
        (0, "night"),
        (5, "night"),
        (6, "morning"),
        (10, "morning"),
        (11, "midday"),
        (14, "midday"),
        (15, "afternoon"),
        (17, "afternoon"),
        (18, "evening"),
        (23, "evening"),
        (None, "unknown"),
    ],
)
def test_fr_03_hour_bucket_boundaries(hour: int | None, bucket: str) -> None:
    assert hour_bucket(hour) == bucket


def test_fr_03_features_values() -> None:
    f = build_feature_frame(sample_rows())
    assert list(f.columns) == list(FEATURE_COLUMNS)
    assert f.loc[0, "text"] == "gopay*kopi kenangan"
    assert f.loc[0, "merchant_key"] == "kopi kenangan"
    assert f.loc[1, "merchant_key"] == "indomaret"
    assert f.loc[1, "hour_bucket"] == "unknown"  # date-only row
    assert f.loc[2, "hour_bucket"] == "night"  # 00:00 is a real time
    assert f.loc[0, "is_weekend"] == 1  # 2025-03-01 is a Saturday
    assert f.loc[2, "is_weekend"] == 0  # 2025-03-25 is a Tuesday
    assert abs(f.loc[3, "log_amount"] - 0.6931471805599453) < 1e-12


def test_fr_03_features_reject_non_positive_amounts() -> None:
    df = sample_rows()
    df.loc[0, "amount"] = Decimal("0")
    with pytest.raises(ValueError, match="amount"):
        build_feature_frame(df)
    with pytest.raises(ValueError, match="amount"):
        online_features(
            TransactionInput(
                "x", None, Decimal("-1"), "expense", "cash", datetime(2025, 1, 1), False
            )
        )


def test_fr_03_missing_columns_rejected() -> None:
    with pytest.raises(ValueError, match="missing input columns"):
        build_feature_frame(sample_rows().drop(columns=["payment_method"]))


def test_feature_version_is_set() -> None:
    assert FEATURE_VERSION == "features-1"


# ---- point-in-time ------------------------------------------------------------------------


def history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "occurred_at": pd.to_datetime(["2025-01-01", "2025-01-05", "2025-01-10", "2025-01-10"]),
            "created_at": pd.to_datetime(
                ["2025-01-01", "2025-01-05", "2025-01-10 09:00", "2025-01-10 08:00"],
                format="ISO8601",
            ),
            "amount": [10.0, 20.0, 30.0, 40.0],
        }
    )


AS_OF = datetime(2025, 1, 11)


def clean_feature(h: pd.DataFrame, as_of: datetime) -> float:
    return float(history_before(h, as_of)["amount"].mean())


def leaky_feature(h: pd.DataFrame, as_of: datetime) -> float:
    return float(h["amount"].mean())  # ignores as_of


def tie_leaky_feature(h: pd.DataFrame, as_of: datetime) -> float:
    return float(h[h["occurred_at"] <= as_of]["amount"].mean())  # uses <= instead of <


def test_point_in_time_accepts_a_correct_feature() -> None:
    assert_point_in_time(clean_feature, history(), AS_OF)


def test_point_in_time_detects_a_leak() -> None:
    with pytest.raises(AssertionError, match="leakage"):
        assert_point_in_time(leaky_feature, history(), AS_OF)


def test_point_in_time_detects_off_by_one_on_ties() -> None:
    with pytest.raises(AssertionError, match="leakage"):
        assert_point_in_time(tie_leaky_feature, history(), datetime(2025, 1, 10))


def test_history_before_is_strict_and_ordered_by_created_at() -> None:
    visible = history_before(history(), datetime(2025, 1, 10, 12))
    assert list(visible["amount"]) == [10.0, 20.0, 40.0, 30.0]  # 08:00 row before 09:00 row
    assert list(history_before(history(), datetime(2025, 1, 10))["amount"]) == [10.0, 20.0]


def test_history_before_does_not_mutate_input() -> None:
    h = history()
    snapshot = h.copy()
    history_before(h, AS_OF)
    assert h.equals(snapshot)


def test_classifier_features_ignore_other_rows() -> None:
    """11.2.1 features depend only on the transaction itself."""
    df = sample_rows()
    alone = build_feature_frame(df.iloc[[0]])
    together = build_feature_frame(df)
    assert_frames_parity(alone, together.iloc[[0]])
