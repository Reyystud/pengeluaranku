"""Prometheus metrics for the ML service (PRD 18.2). No labels carry user data."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# A private registry: the service must not collide with other apps in the same process (tests).
REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)
PREDICTIONS = Counter(
    "predictions_total", "Predictions served", ["model", "decision"], registry=REGISTRY
)
CONFIDENCE = Histogram(
    "prediction_confidence",
    "Top-1 calibrated confidence",
    ["model"],
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
    registry=REGISTRY,
)
INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Inference calls by outcome",
    ["model", "endpoint", "outcome"],
    registry=REGISTRY,
)
PREDICTED_CATEGORY = Counter(
    "predicted_category_total",
    "Predictions per category (about 14 labels: bounded cardinality)",
    ["model_version", "category"],
    registry=REGISTRY,
)
INFERENCE_SECONDS = Histogram(
    "inference_duration_seconds",
    "Feature + model time per call",
    ["model", "endpoint"],
    buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
    registry=REGISTRY,
)
MODEL_LOADED = Gauge(
    "model_loaded_info", "1 for each loaded model", ["model", "version", "alias"], registry=REGISTRY
)
SHADOW_AGREEMENT = Counter(
    "shadow_agreement_total",
    "Shadow (candidate) top-1 vs production top-1, per mirrored item",
    ["model", "agree"],
    registry=REGISTRY,
)
SHADOW_MODEL_LOADED = Gauge(
    "shadow_model_loaded_info",
    "1 for the candidate loaded for shadow",
    ["model", "version"],
    registry=REGISTRY,
)
MODEL_LOAD_FAILURES = Counter(
    "model_load_failures_total", "Refused model loads", ["model", "reason"], registry=REGISTRY
)


def record_model_loaded(model: str, version: str, alias: str) -> None:
    MODEL_LOADED.clear()  # one loaded version per model at a time
    MODEL_LOADED.labels(model, version, alias).set(1)


def record_model_load_failure(model: str, reason: str) -> None:
    MODEL_LOAD_FAILURES.labels(model, reason).inc()


def record_shadow_loaded(model: str, version: str | None) -> None:
    SHADOW_MODEL_LOADED.clear()
    if version is not None:
        SHADOW_MODEL_LOADED.labels(model, version).set(1)
