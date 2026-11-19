"""Pandera schemas for the synthetic dataset (PRD 10.1, 10.3).

``TRANSACTION_COLUMNS`` starts with the product CSV-import columns (PRD 7.2.3) followed by
generator-only columns, so the output file can be fed to the CSV import unchanged.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final

import pandas as pd
import pandera.pandas as pa

from ml.taxonomy import CATEGORIES, MODEL_LABELS

MAX_TRANSACTION_AMOUNT: Final = Decimal("1000000000")

TRANSACTION_TYPES: Final = ("income", "expense", "transfer")
PAYMENT_METHODS: Final = (
    "cash",
    "bank_transfer",
    "debit_card",
    "credit_card",
    "e_wallet",
    "qris",
    "other",
)
ARCHETYPES: Final = (
    "student",
    "young_professional",
    "freelancer",
    "impulsive_spender",
    "subscription_heavy",
)
INCOME_PROFILES: Final = ("allowance", "salary", "irregular")
ANOMALY_TYPES: Final = (
    "amount_spike",
    "frequency_burst",
    "new_merchant_high_value",
    "category_surge",
)
ANOMALY_SEVERITIES: Final = ("low", "medium", "high")

# Product CSV-import columns first (PRD 7.2.3), then generator-only columns (PRD 10.1).
TRANSACTION_COLUMNS: Final = (
    "date",
    "description",
    "amount",
    "type",
    "payment_method",
    "merchant",
    "category",
    "notes",
    "transaction_id",
    "user_id",
    "archetype",
    "true_category",
    "true_merchant",
    "is_anomaly",
    "anomaly_type",
    "anomaly_severity",
    "recurring_series_id",
    "has_time",
)
USER_COLUMNS: Final = (
    "user_id",
    "archetype",
    "income_profile",
    "budget_period_start_day",
    "created_at",
)

_CATEGORY_TYPE: Final = {c.slug: c.transaction_type for c in CATEGORIES}
_DATE_RE: Final = r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?$"
_MAX_CATEGORY_SHARE: Final = 0.80


def _amount_in_range(series: pd.Series[Any]) -> pd.Series[bool]:
    return series.map(lambda v: isinstance(v, Decimal) and Decimal(0) < v <= MAX_TRANSACTION_AMOUNT)


def _amount_has_two_dp(series: pd.Series[Any]) -> pd.Series[bool]:
    return series.map(lambda v: isinstance(v, Decimal) and v == v.quantize(Decimal("0.01")))


def _type_category_consistent(df: pd.DataFrame) -> pd.Series[bool]:
    allowed = df["true_category"].map(_CATEGORY_TYPE)
    return (allowed == "any") | (allowed == df["type"])


def _has_time_matches_date(df: pd.DataFrame) -> pd.Series[bool]:
    return df["has_time"] == (df["date"].str.len() == 16)


def _anomaly_columns_consistent(df: pd.DataFrame) -> pd.Series[bool]:
    flagged = df["is_anomaly"]
    has_type = df["anomaly_type"].notna()
    has_severity = df["anomaly_severity"].notna()
    anomaly_ok = has_type & has_severity & (df["type"] == "expense")
    normal_ok = ~has_type & ~has_severity
    return (flagged & anomaly_ok) | (~flagged & normal_ok)


def _no_dominant_category(df: pd.DataFrame) -> bool:
    shares = df["true_category"].value_counts(normalize=True)
    return bool(len(shares) == 0 or shares.max() <= _MAX_CATEGORY_SHARE)


TRANSACTIONS_SCHEMA: Final = pa.DataFrameSchema(
    {
        "date": pa.Column(str, pa.Check.str_matches(_DATE_RE)),
        "description": pa.Column(str, pa.Check.str_length(1, 200)),
        "amount": pa.Column(
            object,
            [
                pa.Check(_amount_in_range, error="amount must be > 0 and <= max"),
                pa.Check(_amount_has_two_dp, error="amount must have at most 2 dp"),
            ],
        ),
        "type": pa.Column(str, pa.Check.isin(TRANSACTION_TYPES)),
        "payment_method": pa.Column(str, pa.Check.isin(PAYMENT_METHODS)),
        "merchant": pa.Column(str, pa.Check.str_length(1, 100), nullable=True),
        "category": pa.Column(str, nullable=True),
        "notes": pa.Column(str, pa.Check.str_length(1, 500), nullable=True),
        "transaction_id": pa.Column(str, unique=True),
        "user_id": pa.Column(str),
        "archetype": pa.Column(str, pa.Check.isin(ARCHETYPES)),
        "true_category": pa.Column(str, pa.Check.isin(MODEL_LABELS)),
        "true_merchant": pa.Column(str, pa.Check.str_length(1, 100)),
        "is_anomaly": pa.Column(bool),
        "anomaly_type": pa.Column(str, pa.Check.isin(ANOMALY_TYPES), nullable=True),
        "anomaly_severity": pa.Column(str, pa.Check.isin(ANOMALY_SEVERITIES), nullable=True),
        "recurring_series_id": pa.Column(str, nullable=True),
        "has_time": pa.Column(bool),
    },
    checks=[
        pa.Check(_type_category_consistent, error="true_category invalid for type"),
        pa.Check(_has_time_matches_date, error="has_time must match date format"),
        pa.Check(_anomaly_columns_consistent, error="anomaly columns inconsistent"),
        pa.Check(_no_dominant_category, error="one category exceeds 80% of rows"),
    ],
    ordered=True,
    strict=True,
    coerce=False,
)

USERS_SCHEMA: Final = pa.DataFrameSchema(
    {
        "user_id": pa.Column(str, unique=True),
        "archetype": pa.Column(str, pa.Check.isin(ARCHETYPES)),
        "income_profile": pa.Column(str, pa.Check.isin(INCOME_PROFILES)),
        "budget_period_start_day": pa.Column(int, pa.Check.in_range(1, 28)),
        "created_at": pa.Column("datetime64[us, UTC]"),
    },
    ordered=True,
    strict=True,
    coerce=False,
)


def validate_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a transactions frame; raises ``SchemaErrors`` listing every failure."""
    return TRANSACTIONS_SCHEMA.validate(df, lazy=True)


def validate_users(df: pd.DataFrame) -> pd.DataFrame:
    return USERS_SCHEMA.validate(df, lazy=True)
