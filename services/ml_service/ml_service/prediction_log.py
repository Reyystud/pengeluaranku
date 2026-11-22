"""One structured log line per prediction (PRD 18.4).

In GCP a Log Router sink filters ``jsonPayload.event="prediction"`` into BigQuery. The line holds
no description, merchant name, notes or exact amount: only 12-character hashes of the input and of
the merchant key (the drift job tests the latter against the training vocabulary), the
features the drift report needs and the model output (PRD 17.3). It is written to stdout as plain
JSON, which Cloud Run parses into ``jsonPayload``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import math
import sys
from typing import Any

from ml.features.classifier import hour_bucket
from ml.monitoring import merchant_hash
from ml_service.loading.artifact import LoadedClassifier
from ml_service.schemas import ClassifyRequest, ClassifyResponse

log = logging.getLogger("ml_service.prediction")
log.propagate = False  # the line is JSON, not a formatted message


class _StdoutHandler(logging.Handler):
    """Looks ``sys.stdout`` up on every write, so it follows redirection (tests, supervisors)."""

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout.write(record.getMessage() + "\n")
        sys.stdout.flush()


if not any(isinstance(h, _StdoutHandler) for h in log.handlers):
    log.addHandler(_StdoutHandler())
    log.setLevel(logging.INFO)


def input_hash(request: ClassifyRequest) -> str:
    material = f"{request.description.strip().lower()}|{request.amount}|{request.payment_method}"
    return hashlib.sha256(material.encode()).hexdigest()[:12]


def record(
    model: LoadedClassifier,
    request: ClassifyRequest,
    response: ClassifyResponse,
    *,
    shadow: bool = False,
) -> dict[str, Any]:
    line = {
        "event": "prediction",
        "severity": "INFO",
        "model": model.name,
        "model_version": response.model_version,
        "feature_version": response.feature_version,
        "request_id": request.request_id,
        "input_hash": input_hash(request),
        "merchant_hash": merchant_hash(request.merchant_key),  # null without a merchant (PRD 18.3)
        "logged_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "features_summary": {
            "log_amount": round(math.log1p(float(request.amount)), 2),
            "payment_method": request.payment_method,
            "hour_bucket": hour_bucket(request.local_hour),
        },
        "output": {
            "predicted_category": response.predicted_category,
            "confidence": response.confidence,
            "decision": response.decision,
        },
        "shadow": shadow,
        "latency_ms": response.latency_ms,
    }
    log.info(json.dumps(line, separators=(",", ":")))
    return line
