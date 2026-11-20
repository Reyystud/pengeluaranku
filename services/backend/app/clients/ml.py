"""Backend -> ML service client with timeout, one connect retry and a circuit breaker.

PRD 6.3 step 4-5 and 6.4: every failure mode returns an error code and never raises, so saving a
transaction cannot fail because of the ML service. Requests carry no user id (PRD 14.2).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.core.config import Settings
from app.core.metrics import ML_CIRCUIT_STATE, ML_CLIENT_DURATION, ML_CLIENT_REQUESTS

BATCH_LIMIT = 500
WINDOW = 20  # calls considered for the failure-rate rule
MIN_CALLS = 10  # the rate rule needs at least this many calls in the window
CLOSED, HALF_OPEN, OPEN = "closed", "half_open", "open"
_STATE_VALUE = {CLOSED: 0, HALF_OPEN: 1, OPEN: 2}


class CircuitBreaker:
    """Open after N consecutive failures or > 50% failures in the last 20 calls (min 10)."""

    def __init__(
        self,
        consecutive: int = 5,
        open_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._consecutive_limit = consecutive
        self._open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = CLOSED
        self._consecutive = 0
        self._window: deque[bool] = deque(maxlen=WINDOW)
        self._opened_at = 0.0
        self._trial_in_flight = False
        ML_CIRCUIT_STATE.set(0)

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def _set(self, state: str) -> None:
        self._state = state
        ML_CIRCUIT_STATE.set(_STATE_VALUE[state])

    def allow(self) -> bool:
        with self._lock:
            if self._state == CLOSED:
                return True
            if self._state == OPEN:
                if self._clock() - self._opened_at < self._open_seconds:
                    return False
                self._set(HALF_OPEN)
                self._trial_in_flight = False
            if self._trial_in_flight:  # half-open allows one trial request at a time
                return False
            self._trial_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == HALF_OPEN:
                self._set(CLOSED)
                self._window.clear()
            self._trial_in_flight = False
            self._consecutive = 0
            self._window.append(True)

    def record_failure(self) -> None:
        with self._lock:
            if self._state == HALF_OPEN:
                self._trip()
                return
            self._consecutive += 1
            self._window.append(False)
            failures = self._window.count(False)
            too_many = len(self._window) >= MIN_CALLS and failures * 2 > len(self._window)
            if self._consecutive >= self._consecutive_limit or too_many:
                self._trip()

    def _trip(self) -> None:
        self._set(OPEN)
        self._opened_at = self._clock()
        self._trial_in_flight = False
        self._consecutive = 0
        self._window.clear()


class Alternative(BaseModel):
    model_config = ConfigDict(extra="ignore")
    category: str
    confidence: float


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="ignore")
    t_high: float
    t_low: float


class MlPrediction(BaseModel):
    """The part of ``ClassifyResponse`` (PRD 14.2) the backend uses. Extra fields are ignored."""

    model_config = ConfigDict(extra="ignore")
    predicted_category: str
    confidence: float
    decision: Literal["auto_apply", "suggest", "needs_review"]
    alternatives: list[Alternative]
    model_version: str
    feature_version: str
    thresholds: Thresholds
    latency_ms: float


@dataclass(frozen=True)
class MlResult:
    prediction: MlPrediction | None = None
    error: str | None = (
        None  # timeout | unavailable | circuit_open | bad_response | rejected | disabled
    )


class _Failure(Exception):
    def __init__(self, error: str, outcome: str, breaker_failure: bool = True) -> None:
        super().__init__(error)
        self.error, self.outcome, self.breaker_failure = error, outcome, breaker_failure


class MlClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.enabled = bool(settings.ml_service_url)
        self.breaker = breaker or CircuitBreaker(
            settings.ml_circuit_failures, settings.ml_circuit_open_s
        )
        self._timeout = settings.ml_timeout_ms / 1000.0
        self._batch_timeout = settings.ml_batch_timeout_ms / 1000.0
        self._http = (
            httpx.Client(
                base_url=settings.ml_service_url.rstrip("/"),
                timeout=httpx.Timeout(self._timeout),
                transport=transport,
            )
            if self.enabled
            else None
        )

    def close(self) -> None:
        if self._http is not None:
            self._http.close()

    # -- public API ---------------------------------------------------------------------------
    def classify(self, payload: dict[str, Any], request_id: str | None = None) -> MlResult:
        return self._call("classify", "/v1/classify", payload, request_id, self._timeout, 1)[0]

    def classify_batch(
        self, payloads: list[dict[str, Any]], request_id: str | None = None
    ) -> list[MlResult]:
        """One result per payload, in order. A failed chunk fails every item in it."""
        results: list[MlResult] = []
        for start in range(0, len(payloads), BATCH_LIMIT):
            chunk = payloads[start : start + BATCH_LIMIT]
            body = {"request_id": request_id or "batch", "items": chunk}
            results.extend(
                self._call(
                    "classify_batch",
                    "/v1/classify/batch",
                    body,
                    request_id,
                    self._batch_timeout,
                    len(chunk),
                )  # fmt: skip
            )
        return results

    # -- internals ----------------------------------------------------------------------------
    def _call(
        self,
        endpoint: str,
        path: str,
        body: dict[str, Any],
        request_id: str | None,
        timeout: float,
        expected: int,
    ) -> list[MlResult]:
        if self._http is None:
            return [MlResult(error="disabled")] * expected
        if not self.breaker.allow():
            ML_CLIENT_REQUESTS.labels(endpoint, "circuit_open").inc()
            return [MlResult(error="circuit_open")] * expected
        started = time.perf_counter()
        try:
            data = self._post(path, body, request_id, timeout)
            results = self._parse(endpoint, data, expected)
        except _Failure as failure:
            ML_CLIENT_REQUESTS.labels(endpoint, failure.outcome).inc()
            if failure.breaker_failure:
                self.breaker.record_failure()
            else:
                self.breaker.record_success()  # the service answered; our request was refused
            return [MlResult(error=failure.error)] * expected
        finally:
            ML_CLIENT_DURATION.labels(endpoint).observe(time.perf_counter() - started)
        ML_CLIENT_REQUESTS.labels(endpoint, "ok").inc()
        self.breaker.record_success()
        return results

    def _post(self, path: str, body: dict[str, Any], request_id: str | None, timeout: float) -> Any:
        assert self._http is not None
        headers = {"X-Request-ID": request_id} if request_id else {}
        response = None
        for attempt in (1, 2):  # one retry, on connection errors only (never on timeouts)
            try:
                response = self._http.post(
                    path, json=body, headers=headers, timeout=httpx.Timeout(timeout)
                )
                break
            except httpx.TimeoutException as exc:
                raise _Failure("timeout", "timeout") from exc
            except httpx.ConnectError as exc:
                if attempt == 2:
                    raise _Failure("unavailable", "error") from exc
            except httpx.HTTPError as exc:
                raise _Failure("unavailable", "error") from exc
        assert response is not None
        if response.status_code >= 500:
            raise _Failure("unavailable", "error")
        if response.status_code >= 400:
            raise _Failure("rejected", "error", breaker_failure=False)
        try:
            return response.json()
        except ValueError as exc:
            raise _Failure("bad_response", "error") from exc

    @staticmethod
    def _parse(endpoint: str, data: Any, expected: int) -> list[MlResult]:
        try:
            items = data["items"] if endpoint == "classify_batch" else [data]
            parsed = [MlPrediction.model_validate(item) for item in items]
        except (KeyError, TypeError, ValidationError) as exc:
            raise _Failure("bad_response", "error") from exc
        if len(parsed) != expected:
            raise _Failure("bad_response", "error")
        return [MlResult(prediction=p) for p in parsed]
