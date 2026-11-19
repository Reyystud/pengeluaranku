"""Point-in-time helpers (PRD 11.1 rule 2).

Features that use a user's history must call ``history_before`` so only rows strictly before
``as_of`` are visible. ``ml.features.testing.assert_point_in_time`` proves a feature function obeys
this by injecting future rows. The classifier features of 11.2.1 use no history; anomaly and
forecasting features (T-21+) do.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd


def history_before(
    history: pd.DataFrame,
    as_of: datetime,
    time_col: str = "occurred_at",
    tiebreak_col: str = "created_at",
) -> pd.DataFrame:
    """Rows with ``time_col < as_of``, ordered by (time, tiebreak). Does not mutate the input."""
    visible = history[history[time_col] < as_of]
    return visible.sort_values([time_col, tiebreak_col], kind="stable")
