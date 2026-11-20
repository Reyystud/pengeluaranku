"""Smoke test against the model trained by ``make train-local`` (skipped when it is absent)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from ml_service.config import Settings
from ml_service.main import create_app
from ml_support import ROOT, classify_body

pytestmark = pytest.mark.skipif(
    not list((ROOT / "models" / "transaction-classifier").glob("2*/metadata.json")),
    reason="no locally trained classifier in models/",
)


def test_14_2_real_classifier_serves_a_known_merchant() -> None:
    settings = Settings(_env_file=None, model_source="local_dir", models_dir=Path(ROOT / "models"))
    with TestClient(create_app(settings)) as c:
        assert c.get("/readyz").status_code == 200
        body = classify_body(description="STARBUCKS GRAND INDONESIA", merchant_key="starbucks")
        r = c.post("/v1/classify", json=body)
        assert r.status_code == 200
        assert r.json()["predicted_category"] == "food_beverage"
        assert r.json()["decision"] == "auto_apply"
