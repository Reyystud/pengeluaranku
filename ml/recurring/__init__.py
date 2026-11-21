"""Rule-based recurring series detection (PRD 7.8)."""

from ml.recurring.config import Frequency, RecurringConfig, load_recurring_config
from ml.recurring.detector import (
    AmountChange,
    DetectedSeries,
    Occurrence,
    amount_change,
    detect,
    expected_dates,
    match_frequency,
    monthly_equivalent,
    series_status,
)

__all__ = [
    "AmountChange",
    "DetectedSeries",
    "Frequency",
    "Occurrence",
    "RecurringConfig",
    "amount_change",
    "detect",
    "expected_dates",
    "load_recurring_config",
    "match_frequency",
    "monthly_equivalent",
    "series_status",
]
