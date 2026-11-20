"""Classifier endpoints, probes and privacy (PRD 14.1, 14.2, 18.4)."""

from __future__ import annotations

import dataclasses
import logging
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from ml_service.config import Settings
from ml_service.inference import decide
from ml_service.loading.registry import ModelRegistry
from ml_service.main import create_app
from ml_support import classify_body, make_settings

from ml.features import FEATURE_VERSION
from ml.features.classifier import build_feature_frame
from ml.taxonomy import MODEL_LABELS


def test_14_2_classify_returns_the_documented_shape(client: TestClient) -> None:
    r = client.post("/v1/classify", json=classify_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["predicted_category"] == "food_beverage"
    assert set(body) == {
        "predicted_category", "confidence", "decision", "alternatives", "model_version",
        "feature_version", "thresholds", "latency_ms", "shadow",
    }  # fmt: skip
    assert 0.0 <= body["confidence"] <= 1.0 and body["decision"] in {
        "auto_apply", "suggest", "needs_review",
    }  # fmt: skip
    assert len(body["alternatives"]) == 2
    assert all(a["category"] in MODEL_LABELS for a in body["alternatives"])
    assert body["alternatives"][0]["confidence"] >= body["alternatives"][1]["confidence"]
    assert body["model_version"] == "transaction-classifier@run-1"
    assert body["feature_version"] == FEATURE_VERSION and body["shadow"] is None
    assert body["thresholds"] == {"t_high": 0.9, "t_low": 0.6}
    assert body["latency_ms"] >= 0
    assert r.headers["x-request-id"]


def test_fr_03_02_predictions_match_the_offline_pipeline_exactly(
    client: TestClient, toy_artifacts: dict[str, Any], toy_frame: pd.DataFrame
) -> None:
    """Parity (PRD 11.1): the service and the training path give identical probabilities."""
    rows = toy_frame.iloc[::9].reset_index(drop=True)  # includes timed and date-only rows
    expected = toy_artifacts["calibrator"].predict_proba(
        toy_artifacts["model"].predict_proba(
            toy_artifacts["transformer"].transform(build_feature_frame(rows)).tocsr()
        )
    )
    items = []
    for _, row in rows.iterrows():
        date = str(row["date"])
        items.append(
            classify_body(
                description=row["description"],
                merchant_key="",
                amount=f"{row['amount']:.2f}",
                payment_method=row["payment_method"],
                local_hour=int(date[11:13]) if len(date) > 10 else None,
                weekday=pd.Timestamp(date[:10]).weekday(),
            )
        )
    from ml.preprocessing import resolve_merchant

    for item, (_, row) in zip(items, rows.iterrows(), strict=True):
        item["merchant_key"] = resolve_merchant(None, row["description"])[1]
    got = client.post("/v1/classify/batch", json={"request_id": "b", "items": items}).json()[
        "items"
    ]
    for g, p in zip(got, expected, strict=True):
        top = int(np.argmax(p))
        assert g["predicted_category"] == MODEL_LABELS[top]
        assert g["confidence"] == pytest.approx(float(p[top]), abs=1e-6)


def test_14_2_batch_matches_single_calls_and_keeps_order(client: TestClient) -> None:
    items = [
        classify_body(description=f"{label.replace('_', ' ')} shop 2") for label in MODEL_LABELS
    ]
    batch = client.post("/v1/classify/batch", json={"request_id": "b", "items": items})
    assert batch.status_code == 200
    got = batch.json()["items"]
    assert [g["predicted_category"] for g in got] == list(MODEL_LABELS)
    single = client.post("/v1/classify", json=items[5]).json()
    assert got[5]["predicted_category"] == single["predicted_category"]
    assert got[5]["confidence"] == single["confidence"]


def test_14_1_batch_limit_is_500_items(client: TestClient) -> None:
    ok = client.post(
        "/v1/classify/batch", json={"request_id": "b", "items": [classify_body()] * 500}
    )
    assert ok.status_code == 200 and len(ok.json()["items"]) == 500
    too_many = client.post(
        "/v1/classify/batch", json={"request_id": "b", "items": [classify_body()] * 501}
    )
    assert too_many.status_code == 422 and too_many.json()["code"] == "VALIDATION_ERROR"
    empty = client.post("/v1/classify/batch", json={"request_id": "b", "items": []})
    assert empty.status_code == 422


def test_14_1_configured_batch_limit_is_enforced(models_dir: Path) -> None:
    settings = make_settings(models_dir, batch_max_items=2)
    with TestClient(create_app(settings)) as c:
        r = c.post("/v1/classify/batch", json={"request_id": "b", "items": [classify_body()] * 3})
        assert r.status_code == 422 and r.json()["code"] == "BATCH_TOO_LARGE"


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"amount": "0"}, "amount"),
        ({"amount": "-5"}, "amount"),
        ({"amount": "abc"}, "amount"),
        ({"amount": "NaN"}, "amount"),
        ({"amount": "1e30"}, "amount"),
        ({"amount": 1.5}, "amount"),
        ({"amount": True}, "amount"),
        ({"description": ""}, "description"),
        ({"description": "x" * 501}, "description"),
        ({"merchant_key": "m" * 101}, "merchant_key"),
        ({"payment_method": "bitcoin"}, "payment_method"),
        ({"transaction_type": "refund"}, "transaction_type"),
        ({"local_hour": 24}, "local_hour"),
        ({"local_hour": -1}, "local_hour"),
        ({"weekday": 7}, "weekday"),
        ({"request_id": ""}, "request_id"),
        ({"user_id": "u-1"}, "user_id"),  # extra fields are rejected (and user_id is never taken)
    ],
)
def test_14_1_invalid_input_is_rejected(
    client: TestClient, change: dict[str, Any], field: str
) -> None:
    r = client.post("/v1/classify", json=classify_body(**change))
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR" and body["errors"][0]["field"] == field
    assert r.headers["content-type"].startswith("application/problem+json")


def test_14_2_local_hour_null_means_unknown_time(client: TestClient) -> None:
    timed = client.post("/v1/classify", json=classify_body(local_hour=3))
    untimed = client.post("/v1/classify", json=classify_body(local_hour=None))
    assert timed.status_code == untimed.status_code == 200
    required = classify_body()
    del required["local_hour"]
    assert client.post("/v1/classify", json=required).status_code == 422  # must be explicit


def test_14_2_unknown_feature_version_is_refused(client: TestClient) -> None:
    r = client.post("/v1/classify", json=classify_body(feature_version="features-9"))
    assert r.status_code == 422 and r.json()["code"] == "FEATURE_VERSION_MISMATCH"
    batch = client.post(
        "/v1/classify/batch",
        json={"request_id": "b", "items": [classify_body(), classify_body(feature_version="x")]},
    )
    assert batch.status_code == 422
    assert batch.json()["errors"][0]["field"] == "items.1.feature_version"


@pytest.mark.parametrize(
    ("confidence", "t_high", "t_low", "expected"),
    [
        (0.95, 0.9, 0.6, "auto_apply"),
        (0.9, 0.9, 0.6, "auto_apply"),
        (0.89, 0.9, 0.6, "suggest"),
        (0.6, 0.9, 0.6, "suggest"),
        (0.59, 0.9, 0.6, "needs_review"),
        (0.89, 0.9, 0.9, "needs_review"),  # no suggest band (current model)
        (0.9, 0.9, 0.9, "auto_apply"),
    ],
)
def test_7_3_4_decision_follows_the_thresholds(
    confidence: float, t_high: float, t_low: float, expected: str
) -> None:
    assert decide(confidence, t_high, t_low) == expected


def test_7_3_4_thresholds_come_from_metadata_not_code(models_dir: Path) -> None:
    import json

    meta = models_dir / "transaction-classifier" / "run-1" / "metadata.json"
    data = json.loads(meta.read_text())
    data["decision_thresholds"] = {"t_high": 0.0, "t_low": 0.0}
    meta.write_text(json.dumps(data))
    with TestClient(create_app(make_settings(models_dir))) as c:
        assert c.get("/readyz").status_code == 200
        r = c.post("/v1/classify", json=classify_body()).json()
        assert r["decision"] == "auto_apply" and r["thresholds"] == {"t_high": 0.0, "t_low": 0.0}


def test_11_5_probes_and_models_listing(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["checks"] == {"classifier": "ok"}
    listed = client.get("/v1/models").json()
    assert listed["last_load_error"] is None
    (m,) = listed["models"]
    assert m["name"] == "transaction-classifier" and m["version"] == "run-1"
    assert m["feature_version"] == FEATURE_VERSION and m["thresholds"] == {
        "t_high": 0.9,
        "t_low": 0.6,
    }


def test_11_4_corrupted_model_keeps_the_service_alive_but_not_ready(models_dir: Path) -> None:
    joblib_file = models_dir / "transaction-classifier" / "run-1" / "model.joblib"
    with joblib_file.open("ab") as fh:
        fh.write(b"tampered")
    with TestClient(create_app(make_settings(models_dir))) as c:
        assert c.get("/healthz").status_code == 200
        ready = c.get("/readyz")
        assert ready.status_code == 503 and ready.json()["code"] == "SERVICE_UNAVAILABLE"
        assert ready.json()["errors"][0]["code"] == "HASH_MISMATCH"
        r = c.post("/v1/classify", json=classify_body())
        assert r.status_code == 503 and r.json()["code"] == "MODEL_NOT_AVAILABLE"
        assert c.get("/v1/models").json() == {"models": [], "last_load_error": "HASH_MISMATCH"}
        assert "model_load_failures_total" in c.get("/metrics").text


def test_11_5_no_model_directory_is_not_ready(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path / "empty"))) as c:
        assert c.get("/readyz").json()["errors"][0]["code"] == "SOURCE_UNAVAILABLE"


def test_11_5_a_failed_reload_keeps_the_previous_model(models_dir: Path) -> None:
    settings = make_settings(models_dir)
    registry = ModelRegistry(settings)
    assert registry.load() is True
    first = registry.classifier
    run = models_dir / "transaction-classifier" / "run-1"
    shutil.copytree(run, models_dir / "transaction-classifier" / "run-2")
    with (models_dir / "transaction-classifier" / "run-2" / "model.joblib").open("ab") as fh:
        fh.write(b"x")
    assert registry.load() is False  # newest run is corrupt
    assert registry.classifier is first and registry.error is not None
    assert registry.error.code == "HASH_MISMATCH"
    registry.check_ready()  # still ready: the old model keeps serving


def test_14_1_google_id_token_auth_is_not_silently_ignored(models_dir: Path) -> None:
    settings = Settings(_env_file=None, model_source="local_dir", models_dir=models_dir,
                        ml_auth="google_id_token")  # fmt: skip
    with pytest.raises(RuntimeError, match="not implemented"):
        create_app(settings)


def test_18_2_metrics_expose_predictions_and_loaded_model(client: TestClient) -> None:
    client.post("/v1/classify", json=classify_body())
    text = client.get("/metrics").text
    assert "predictions_total{decision=" in text and 'model="transaction-classifier"' in text
    assert (
        'model_loaded_info{alias="local",model="transaction-classifier",version="run-1"} 1.0'
        in text
    )
    assert 'http_requests_total{method="POST",route="/v1/classify",status="200"}' in text
    assert "prediction_confidence_bucket" in text


def test_18_4_text_is_never_logged_or_echoed(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "RAHASIA-WARUNG-XYZ"
    with caplog.at_level(logging.DEBUG):
        ok = client.post(
            "/v1/classify", json=classify_body(description=secret, merchant_key=secret.lower())
        )
        bad = client.post("/v1/classify", json=classify_body(description=secret, amount="-1"))
        client.post("/v1/classify", json=classify_body(description=secret, user_id=secret))
    assert ok.status_code == 200 and bad.status_code == 422
    assert secret not in bad.text and secret.lower() not in ok.text
    logged = "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert secret not in logged and secret.lower() not in logged and "45000" not in logged
    assert "request" in logged  # the access line is there, without bodies


def test_14_1_request_id_header_is_propagated(client: TestClient) -> None:
    r = client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    missing = client.get("/v1/nothing")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert missing.json()["request_id"] == missing.headers["x-request-id"]


def test_decision_dataclass_is_frozen() -> None:
    from ml_service.loading.artifact import LoadedClassifier

    assert dataclasses.is_dataclass(LoadedClassifier)
    assert LoadedClassifier.__dataclass_params__.frozen  # type: ignore[attr-defined]
