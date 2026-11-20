"""Prometheus metrics for the backend (PRD 18.2). Route labels use templates, never raw paths."""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["service", "route", "method", "status"]
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["service", "route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ML_CLIENT_REQUESTS = Counter(
    "ml_client_requests_total", "Calls to the ML service", ["endpoint", "outcome"]
)
ML_CLIENT_DURATION = Histogram(
    "ml_client_duration_seconds",
    "ML service call duration",
    ["endpoint"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
ML_CIRCUIT_STATE = Gauge("ml_circuit_state", "ML circuit breaker: 0 closed, 1 half-open, 2 open")
CATEGORIZE_PREVIEW = Counter(
    "categorize_preview_total", "categorize-preview calls (no user data in labels)", ["decision"]
)
