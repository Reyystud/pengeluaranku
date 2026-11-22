"""Run the candidate on requests production already answered (PRD 16.4 items 1 and 2).

``run_candidate`` is scheduled as a FastAPI background task, so it starts after the response has
been sent: it adds no latency to the response path. It never raises: a failing candidate must not
affect production, it is counted and logged instead.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from ml_service import prediction_log
from ml_service.inference import classify
from ml_service.loading.registry import ModelRegistry
from ml_service.metrics import INFERENCE_REQUESTS, INFERENCE_SECONDS, SHADOW_AGREEMENT
from ml_service.schemas import ClassifyRequest, ClassifyResponse

log = logging.getLogger("ml_service.shadow")


def run_candidate(
    registry: ModelRegistry,
    items: Sequence[ClassifyRequest],
    production: Sequence[ClassifyResponse],
    endpoint: str,
) -> None:
    candidate = registry.candidate
    if candidate is None or not registry.shadow_active:
        return
    try:
        with INFERENCE_SECONDS.labels(candidate.name, "shadow").time():
            results = classify(candidate, list(items))
    except Exception as exc:
        INFERENCE_REQUESTS.labels(candidate.name, "shadow", "error").inc(len(items))
        log.warning("shadow inference failed", extra={"error_type": type(exc).__name__})
        for item in items:
            try:
                prediction_log.record_shadow_error(candidate, item, exc)
            except Exception:  # logging must not fail either
                log.exception("shadow error line failed")
        return
    INFERENCE_REQUESTS.labels(candidate.name, "shadow", "ok").inc(len(items))
    for item, shadow_result, prod_result in zip(items, results, production, strict=True):
        agree = shadow_result.predicted_category == prod_result.predicted_category
        SHADOW_AGREEMENT.labels(candidate.name, "true" if agree else "false").inc()
        try:
            prediction_log.record(candidate, item, shadow_result, shadow=True)
        except Exception:
            log.exception("shadow prediction line failed")
