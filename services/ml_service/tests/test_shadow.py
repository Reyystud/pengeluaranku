"""Shadow mode (PRD 16.4): the candidate runs after the response, is only logged, never breaks
production, and its agreement with production is counted."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from ml_service import inference
from ml_service.loading.registry import ModelRegistry
from ml_service.loading.sources import LocalDirSource
from ml_service.main import create_app
from ml_service.metrics import REGISTRY
from ml_support import ROOT, classify_body, make_settings, write_model_dir

from ml.classification.calibration import IsotonicOvR
from ml.classification.pipeline import make_model
from ml.features.classifier import build_feature_frame
from ml.taxonomy import MODEL_LABELS

NAME = "transaction-classifier"


@pytest.fixture(scope="module")
def candidate_artifacts(toy_artifacts: dict[str, Any], toy_frame: pd.DataFrame) -> dict[str, Any]:
    """Same transformer, labels rotated by one: a candidate that disagrees with production."""
    cfg = yaml.safe_load((ROOT / "config/train/classifier.yaml").read_text())
    X = toy_artifacts["transformer"].transform(build_feature_frame(toy_frame)).tocsr()
    y = toy_frame["label"].map({n: i for i, n in enumerate(MODEL_LABELS)}).to_numpy()
    y = (y + 1) % len(MODEL_LABELS)
    model = make_model("logreg", cfg, 42).fit(X, y)
    raw = np.asarray(model.predict_proba(X), dtype=np.float64)
    calibrator = IsotonicOvR().fit(raw, y.astype(np.int64))
    return {"transformer": toy_artifacts["transformer"], "model": model, "calibrator": calibrator}


def agreement(agree: str) -> float:
    return float(
        REGISTRY.get_sample_value("shadow_agreement_total", {"model": NAME, "agree": agree}) or 0.0
    )


@pytest.fixture
def shadow_client(
    models_dir: Path, candidate_artifacts: dict[str, Any]
) -> Iterator[tuple[TestClient, ModelRegistry]]:
    write_model_dir(models_dir / NAME / "cand-1", candidate_artifacts)
    settings = make_settings(models_dir, shadow_enabled=True)
    registry = ModelRegistry(settings, candidate_source=LocalDirSource(models_dir, NAME, "cand-1"))
    with TestClient(create_app(settings, registry)) as c:
        yield c, registry


def prediction_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    out = capsys.readouterr().out
    return [json.loads(x) for x in out.splitlines() if x.startswith("{")]


def test_fr_16_4_candidate_is_loaded_and_listed_without_affecting_readiness(
    shadow_client: tuple[TestClient, ModelRegistry],
) -> None:
    client, registry = shadow_client
    assert registry.shadow_active and registry.candidate is not None
    assert client.get("/readyz").status_code == 200
    models = client.get("/v1/models").json()["models"]
    assert [m.get("shadow") for m in models] == [None, True]
    assert models[0]["version"] == "run-1" and models[1]["version"] == "cand-1"


def test_fr_16_4_response_is_the_production_answer_and_shadow_is_only_logged(
    shadow_client: tuple[TestClient, ModelRegistry], capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = shadow_client
    capsys.readouterr()
    r = client.post("/v1/classify", json=classify_body(request_id="shadow-1"))
    assert r.status_code == 200
    body = r.json()
    assert body["model_version"].endswith("run-1") and body["shadow"] is None
    lines = [x for x in prediction_lines(capsys) if x["event"] == "prediction"]
    assert [(x["shadow"], x["model_version"].endswith("cand-1")) for x in lines] == [
        (False, False),
        (True, True),
    ]
    assert lines[0]["request_id"] == lines[1]["request_id"] == "shadow-1"
    assert lines[0]["input_hash"] == lines[1]["input_hash"]
    assert "description" not in json.dumps(lines)  # no user text in the shadow line either


def test_fr_16_4_agreement_is_counted_per_item_for_batches(
    shadow_client: tuple[TestClient, ModelRegistry],
) -> None:
    client, _ = shadow_client
    before = agreement("true") + agreement("false")
    items = [
        classify_body(request_id=f"b{i}", description=f"{lab} shop 2")
        for i, lab in enumerate(("groceries", "health", "utilities"))
    ]
    r = client.post("/v1/classify/batch", json={"request_id": "batch", "items": items})
    assert r.status_code == 200 and len(r.json()["items"]) == 3
    assert agreement("true") + agreement("false") == before + 3
    assert agreement("false") > 0  # the rotated candidate disagrees


def test_fr_16_4_a_failing_candidate_never_affects_the_response(
    shadow_client: tuple[TestClient, ModelRegistry],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, registry = shadow_client
    candidate = registry.candidate
    real = inference.classify

    def boom(model: Any, requests: Any) -> Any:
        if model is candidate:
            raise RuntimeError("secret description leaked here")
        return real(model, requests)

    monkeypatch.setattr("ml_service.shadow.runner.classify", boom)
    capsys.readouterr()
    r = client.post("/v1/classify", json=classify_body(request_id="shadow-err"))
    assert r.status_code == 200
    errors = [x for x in prediction_lines(capsys) if x["event"] == "shadow_error"]
    assert len(errors) == 1 and errors[0]["error_type"] == "RuntimeError"
    assert errors[0]["request_id"] == "shadow-err"
    assert "secret" not in json.dumps(errors)  # class name only, never the message


def test_fr_16_4_same_version_as_production_means_no_shadow(
    models_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(models_dir, shadow_enabled=True)
    registry = ModelRegistry(settings, candidate_source=LocalDirSource(models_dir, NAME, "run-1"))
    with TestClient(create_app(settings, registry)) as client:
        assert not registry.shadow_active
        capsys.readouterr()
        assert client.post("/v1/classify", json=classify_body()).status_code == 200
        assert [x["shadow"] for x in prediction_lines(capsys)] == [False]


def test_fr_16_4_shadow_is_off_by_default(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert client.post("/v1/classify", json=classify_body()).status_code == 200
    assert [x["shadow"] for x in prediction_lines(capsys)] == [False]
    assert len(client.get("/v1/models").json()["models"]) == 1


def test_fr_16_4_refresh_candidate_follows_the_alias(
    shadow_client: tuple[TestClient, ModelRegistry],
) -> None:
    _, registry = shadow_client
    assert registry.refresh_candidate() is False  # same version
    registry._candidate_source = LocalDirSource(Path("/nonexistent"), NAME, "x")  # alias gone
    assert registry.refresh_candidate() is True and registry.candidate is None
    assert registry.refresh_candidate() is False
