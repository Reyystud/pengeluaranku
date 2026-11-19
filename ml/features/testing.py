"""Reusable harnesses for the leakage and parity requirements (PRD 11.1, 21.2)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

FeatureFn = Callable[[pd.DataFrame, datetime], Any]


def assert_point_in_time(
    feature_fn: FeatureFn,
    history: pd.DataFrame,
    as_of: datetime,
    time_col: str = "occurred_at",
    n_future: int = 5,
) -> None:
    """Fail if ``feature_fn(history, as_of)`` changes when rows at or after ``as_of`` are added.

    Future rows are copies of existing rows shifted to ``as_of`` and later, with scrambled
    numeric values, so any leak shows up as a different result.
    """
    before = feature_fn(history, as_of)
    template = history.tail(n_future).copy()
    future = []
    for i in range(3):
        extra = template.copy()
        extra[time_col] = as_of + timedelta(days=i)  # i == 0 is a tie with as_of itself
        for col in extra.select_dtypes("number").columns:
            extra[col] = extra[col] * 1000 + 12345
        future.append(extra)
    polluted = pd.concat([history, *future], ignore_index=True)
    after = feature_fn(polluted, as_of)
    if not _equal(before, after):
        raise AssertionError("features changed when future rows were injected (leakage)")


def assert_frames_parity(
    batch: pd.DataFrame,
    online: pd.DataFrame,
    tolerance: float = 1e-6,
) -> None:
    """Batch vs online features: floats within ``tolerance``, everything else exactly equal."""
    if list(batch.columns) != list(online.columns):
        raise AssertionError(f"columns differ: {list(batch.columns)} vs {list(online.columns)}")
    if len(batch) != len(online):
        raise AssertionError(f"row counts differ: {len(batch)} vs {len(online)}")
    left, right = batch.reset_index(drop=True), online.reset_index(drop=True)
    for col in left.columns:
        if pd.api.types.is_float_dtype(left[col]):
            if not np.allclose(left[col], right[col].astype("float64"), rtol=0, atol=tolerance):
                raise AssertionError(f"float column {col!r} differs by more than {tolerance}")
        elif not left[col].astype(object).equals(right[col].astype(object)):
            bad = int((left[col].astype(object) != right[col].astype(object)).sum())
            raise AssertionError(f"column {col!r} differs in {bad} rows")


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, pd.DataFrame):
        return bool(a.reset_index(drop=True).equals(b.reset_index(drop=True)))
    if isinstance(a, pd.Series):
        return bool(a.reset_index(drop=True).equals(b.reset_index(drop=True)))
    return bool(a == b)
