"""Probes and metrics (PRD 13.2).

``/healthz`` has no dependencies; ``/readyz`` runs the registered readiness checks.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.errors import ProblemError

router = APIRouter(tags=["health"])

ReadinessCheck = Callable[[], None]


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches the database or other services."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> dict[str, object]:
    """Readiness: every registered check passes (T-12 adds database and migrations checks)."""
    checks: dict[str, ReadinessCheck] = request.app.state.readiness_checks
    failed: list[dict[str, str]] = []
    results: dict[str, str] = {}
    for name, check in checks.items():
        try:
            check()
            results[name] = "ok"
        except Exception as exc:  # report the class only; messages may contain connection details
            results[name] = "failed"
            failed.append({"field": name, "code": "CHECK_FAILED", "message": type(exc).__name__})
    if failed:
        raise ProblemError(
            503, "SERVICE_UNAVAILABLE", "Service unavailable", "Not ready.", errors=failed
        )
    return {"status": "ok", "checks": results}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
