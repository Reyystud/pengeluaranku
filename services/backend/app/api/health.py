"""Probes and metrics (PRD 13.2).

``/healthz`` has no dependencies; ``/readyz`` runs the registered readiness checks.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select

from app.core.errors import ProblemError
from app.core.metrics import OUTBOX_OLDEST_AGE, OUTBOX_PENDING
from app.models import OutboxEvent
from app.models.base import utcnow

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


def refresh_outbox_gauges(request: Request) -> None:
    """Outbox backlog and age, read at scrape time with one indexed query (PRD 18.2)."""
    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return
    try:
        with factory() as session:
            count, oldest = session.execute(
                select(func.count(), func.min(OutboxEvent.created_at)).where(
                    OutboxEvent.published_at.is_(None)
                )
            ).one()
    except Exception:  # a scrape must not fail because the database is down
        return
    OUTBOX_PENDING.set(count)
    OUTBOX_OLDEST_AGE.set(0 if oldest is None else max(0.0, (utcnow() - oldest).total_seconds()))


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    refresh_outbox_gauges(request)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
