"""Probes and metrics (PRD 14.2)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ml_service.errors import ProblemError
from ml_service.loading.artifact import ModelLoadError
from ml_service.loading.registry import ModelRegistry
from ml_service.metrics import REGISTRY

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request) -> dict[str, object]:
    """200 only when every required model is loaded; the reason code is the only detail given."""
    registry: ModelRegistry = request.app.state.registry
    try:
        registry.check_ready()
    except ModelLoadError as exc:
        raise ProblemError(
            503,
            "SERVICE_UNAVAILABLE",
            "Service unavailable",
            "Not ready.",
            errors=[{"field": "classifier", "code": exc.code, "message": "model not loaded"}],
        ) from exc
    return {"status": "ok", "checks": {"classifier": "ok"}}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
