"""GET /v1/models: what is loaded (PRD 11.5)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ml_service.loading.registry import ModelRegistry

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models")
def list_models(request: Request) -> dict[str, Any]:
    registry: ModelRegistry = request.app.state.registry
    c = registry.classifier
    loaded = []
    if c is not None:
        loaded.append(
            {
                "name": c.name,
                "version": c.version,
                "alias": c.alias,
                "loaded_at": c.loaded_at.isoformat(),
                "feature_version": c.feature_version,
                "taxonomy_version": c.taxonomy_version,
                "thresholds": {"t_high": c.t_high, "t_low": c.t_low},
                "labels": len(c.labels),
            }
        )
    return {"models": loaded, "last_load_error": registry.error.code if registry.error else None}
