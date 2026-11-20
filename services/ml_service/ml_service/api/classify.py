"""Classification endpoints (PRD 14.2)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ml_service.errors import ProblemError
from ml_service.inference import classify
from ml_service.loading.artifact import LoadedClassifier
from ml_service.loading.registry import ModelRegistry
from ml_service.metrics import CONFIDENCE, INFERENCE_SECONDS, PREDICTIONS
from ml_service.schemas import BatchRequest, BatchResponse, ClassifyRequest, ClassifyResponse

router = APIRouter(prefix="/v1", tags=["classify"])


def _model(request: Request) -> LoadedClassifier:
    registry: ModelRegistry = request.app.state.registry
    classifier = registry.classifier
    if classifier is None:
        raise ProblemError(
            503, "MODEL_NOT_AVAILABLE", "Model not available", "The classifier is not loaded."
        )
    return classifier


def _check_versions(model: LoadedClassifier, items: list[ClassifyRequest]) -> None:
    bad = [i for i, r in enumerate(items) if r.feature_version != model.feature_version]
    if bad:
        raise ProblemError(
            422,
            "FEATURE_VERSION_MISMATCH",
            "Feature version mismatch",
            f"The loaded model uses {model.feature_version}.",
            errors=[
                {
                    "field": f"items.{i}.feature_version",
                    "code": "FEATURE_VERSION_MISMATCH",
                    "message": "Unsupported feature version.",
                }
                for i in bad[:10]
            ],
        )


def _run(
    model: LoadedClassifier, items: list[ClassifyRequest], endpoint: str
) -> list[ClassifyResponse]:
    with INFERENCE_SECONDS.labels(model.name, endpoint).time():
        results = classify(model, items)
    for r in results:
        PREDICTIONS.labels(model.name, r.decision).inc()
        CONFIDENCE.labels(model.name).observe(r.confidence)
    return results


@router.post("/classify", response_model=ClassifyResponse)
def classify_one(body: ClassifyRequest, request: Request) -> ClassifyResponse:
    model = _model(request)
    _check_versions(model, [body])
    return _run(model, [body], "classify")[0]


@router.post("/classify/batch", response_model=BatchResponse)
def classify_batch(body: BatchRequest, request: Request) -> BatchResponse:
    model = _model(request)
    limit = request.app.state.settings.batch_max_items
    if len(body.items) > limit:
        raise ProblemError(
            422, "BATCH_TOO_LARGE", "Batch too large", f"At most {limit} items per batch."
        )
    _check_versions(model, body.items)
    return BatchResponse(items=_run(model, body.items, "classify_batch"))
