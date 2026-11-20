"""Baseline anomaly detector (PRD 7.6.2): robust z-score, Poisson burst, new merchant, surge.

Pure Python on plain numbers, so the backend can run it in-process on SQL-computed history and the
evaluation script can run the same code over a dataset. Thresholds live in ``config/anomaly.yaml``.
"""

from ml.anomaly_detection.baseline import (
    CategoryPrior,
    Detection,
    Reason,
    Transaction,
    UserHistory,
    detect,
    detect_surge,
)
from ml.anomaly_detection.config import AnomalyConfig, load_anomaly_config

__all__ = [
    "AnomalyConfig",
    "CategoryPrior",
    "Detection",
    "Reason",
    "Transaction",
    "UserHistory",
    "detect",
    "detect_surge",
    "load_anomaly_config",
]
