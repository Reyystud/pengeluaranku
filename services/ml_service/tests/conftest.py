"""A tiny classifier trained inside the test run, so CI needs no local models/ directory."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))  # ml_support is imported by name

from ml_service.main import create_app  # noqa: E402
from ml_support import ROOT, make_settings, toy_rows, write_model_dir  # noqa: E402

from ml.classification.calibration import IsotonicOvR  # noqa: E402
from ml.classification.pipeline import build_transformer, make_model  # noqa: E402
from ml.features.classifier import build_feature_frame  # noqa: E402
from ml.taxonomy import MODEL_LABELS  # noqa: E402


@pytest.fixture(scope="session")
def toy_frame() -> pd.DataFrame:
    return toy_rows()


@pytest.fixture(scope="session")
def toy_artifacts(toy_frame: pd.DataFrame) -> dict[str, Any]:
    cfg = yaml.safe_load((ROOT / "config/train/classifier.yaml").read_text())
    features = build_feature_frame(toy_frame)
    transformer = build_transformer(cfg)
    X = transformer.fit_transform(features).tocsr()
    y = toy_frame["label"].map({name: i for i, name in enumerate(MODEL_LABELS)}).to_numpy()
    model = make_model("logreg", cfg, 42).fit(X, y)
    raw = np.asarray(model.predict_proba(X), dtype=np.float64)
    calibrator = IsotonicOvR().fit(raw, y.astype(np.int64))
    return {"transformer": transformer, "model": model, "calibrator": calibrator}


@pytest.fixture(scope="session")
def toy_model_dir(tmp_path_factory: pytest.TempPathFactory, toy_artifacts: dict[str, Any]) -> Path:
    return write_model_dir(tmp_path_factory.mktemp("toy") / "run-1", toy_artifacts)


@pytest.fixture
def models_dir(tmp_path: Path, toy_model_dir: Path) -> Path:
    """models/transaction-classifier/<run>/ holding a fresh copy of the toy model."""
    run = tmp_path / "models" / "transaction-classifier" / "run-1"
    shutil.copytree(toy_model_dir, run)
    return tmp_path / "models"


@pytest.fixture
def client(models_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(make_settings(models_dir))) as c:
        yield c
