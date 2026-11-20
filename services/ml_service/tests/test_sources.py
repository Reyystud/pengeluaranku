"""Model sources: local directory and the MLflow registry (PRD 11.5)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ml_service.config import Settings
from ml_service.loading.artifact import ModelLoadError
from ml_service.loading.registry import ModelRegistry
from ml_service.loading.sources import LocalDirSource, MlflowSource
from ml_service.main import create_app
from ml_support import classify_body


def test_11_5_local_dir_picks_the_newest_run_or_the_requested_one(tmp_path: Path) -> None:
    root = tmp_path / "transaction-classifier"
    for name in ("20260101-000000", "20260301-000000", "20260201-000000"):
        (root / name).mkdir(parents=True)
    assert (
        LocalDirSource(tmp_path, "transaction-classifier", None).resolve().version
        == "20260301-000000"
    )
    pinned = LocalDirSource(tmp_path, "transaction-classifier", "20260101-000000").resolve()
    assert pinned.version == "20260101-000000" and pinned.alias is None
    for source in (
        LocalDirSource(tmp_path, "transaction-classifier", "nope"),
        LocalDirSource(tmp_path, "other-model", None),
    ):
        with pytest.raises(ModelLoadError) as exc:
            source.resolve()
        assert exc.value.code == "SOURCE_UNAVAILABLE"


@pytest.fixture
def mlflow_store(tmp_path: Path, toy_model_dir: Path) -> tuple[str, Path]:
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    import mlflow
    from mlflow import MlflowClient

    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    artifact_root = tmp_path / "artifacts"
    client = MlflowClient(tracking_uri=uri, registry_uri=uri)
    experiment = client.create_experiment("toy", artifact_location=artifact_root.as_uri())
    run = client.create_run(experiment)
    client.log_artifacts(run.info.run_id, str(toy_model_dir), artifact_path="model")
    client.set_terminated(run.info.run_id)
    client.create_registered_model("transaction-classifier")
    version = client.create_model_version(
        "transaction-classifier", source=f"runs:/{run.info.run_id}/model", run_id=run.info.run_id
    )
    client.set_registered_model_alias("transaction-classifier", "production", version.version)
    assert mlflow  # imported for its side effects on the client
    return uri, tmp_path / "cache"


def test_11_5_loads_models_at_alias_from_mlflow(mlflow_store: tuple[str, Path]) -> None:
    uri, cache = mlflow_store
    settings = Settings(
        _env_file=None, model_source="mlflow", mlflow_tracking_uri=uri, models_dir=cache
    )
    with TestClient(create_app(settings)) as c:
        assert c.get("/readyz").status_code == 200
        (m,) = c.get("/v1/models").json()["models"]
        assert m["version"] == "1" and m["alias"] == "production"
        r = c.post("/v1/classify", json=classify_body())
        assert r.json()["model_version"] == "transaction-classifier@1"
        assert 'alias="production"' in c.get("/metrics").text


def test_11_5_missing_alias_or_unreachable_registry_is_not_ready(
    mlflow_store: tuple[str, Path], tmp_path: Path
) -> None:
    uri, cache = mlflow_store
    missing = ModelRegistry(
        Settings(
            _env_file=None,
            model_source="mlflow",
            mlflow_tracking_uri=uri,
            models_dir=cache,
            classifier_alias="candidate",
        )  # fmt: skip
    )
    assert missing.load() is False and missing.error and missing.error.code == "SOURCE_UNAVAILABLE"
    with pytest.raises(ModelLoadError):
        missing.check_ready()
    with pytest.raises(ModelLoadError):
        missing.require_classifier()
    source: Any = MlflowSource(
        "sqlite:////nonexistent-dir/x.db", "transaction-classifier", "production", tmp_path
    )
    with pytest.raises(ModelLoadError) as exc:
        source.resolve()
    assert exc.value.code == "SOURCE_UNAVAILABLE"


def test_11_4_a_tampered_mlflow_artifact_is_refused(mlflow_store: tuple[str, Path]) -> None:
    uri, cache = mlflow_store
    store = Path(uri.removeprefix("sqlite:///")).parent / "artifacts"
    (joblib,) = store.rglob("model.joblib")
    with joblib.open("ab") as fh:
        fh.write(b"tampered")
    registry = ModelRegistry(
        Settings(_env_file=None, model_source="mlflow", mlflow_tracking_uri=uri, models_dir=cache)
    )
    assert registry.load() is False
    assert registry.error is not None and registry.error.code == "HASH_MISMATCH"
