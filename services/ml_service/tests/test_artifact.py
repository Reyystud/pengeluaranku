"""Artifact verification and loading (PRD 11.4, 11.5, 11.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import pytest
from ml_service.loading.artifact import ModelLoadError, load_classifier, sha256_file
from ml_support import THRESHOLDS, write_model_dir

from ml.features import FEATURE_VERSION

NAME = "transaction-classifier"


def load(directory: Path) -> Any:
    return load_classifier(directory, version="v1", alias="production", expected_name=NAME)


def rewrite_metadata(directory: Path, **changes: Any) -> None:
    path = directory / "metadata.json"
    meta = json.loads(path.read_text())
    meta.update(changes)
    path.write_text(json.dumps(meta))


@pytest.fixture
def run_dir(tmp_path: Path, toy_artifacts: dict[str, Any]) -> Path:
    return write_model_dir(tmp_path / "run", toy_artifacts)


def test_11_5_valid_artifact_loads_with_thresholds_from_metadata(run_dir: Path) -> None:
    model = load(run_dir)
    assert model.label == f"{NAME}@v1" and model.alias == "production"
    assert (model.t_high, model.t_low) == (THRESHOLDS["t_high"], THRESHOLDS["t_low"])
    assert model.feature_version == FEATURE_VERSION and len(model.labels) == 19


def test_11_4_hash_mismatch_refuses_and_never_unpickles(
    run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (run_dir / "model.joblib").open("ab") as fh:
        fh.write(b"tampered")

    def boom(*_: Any, **__: Any) -> None:
        raise AssertionError("joblib.load must not run on an unverified file")

    monkeypatch.setattr(joblib, "load", boom)
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "HASH_MISMATCH"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"artifact_sha256": {}}, "HASH_MISSING"),
        ({"artifact_sha256": None}, "HASH_MISSING"),
        ({"artifact_sha256": {"other.bin": "00"}}, "HASH_MISSING"),
        ({"artifact_sha256": {"model.joblib": "0" * 64, "gone.bin": "0" * 64}}, "HASH_MISMATCH"),
        ({"decision_thresholds": None}, "THRESHOLDS_MISSING"),
        ({"decision_thresholds": {"t_high": 0.8}}, "THRESHOLDS_INVALID"),
        ({"decision_thresholds": {"t_high": 0.5, "t_low": 0.8}}, "THRESHOLDS_INVALID"),
        ({"decision_thresholds": {"t_high": 1.5, "t_low": 0.2}}, "THRESHOLDS_INVALID"),
        ({"decision_thresholds": {"t_high": "x", "t_low": 0.2}}, "THRESHOLDS_INVALID"),
        ({"feature_version": "features-9"}, "FEATURE_VERSION_UNSUPPORTED"),
        ({"taxonomy_version": "taxonomy-9"}, "TAXONOMY_MISMATCH"),
        ({"labels": ["food_beverage"]}, "LABELS_MISMATCH"),
        ({"model_name": "anomaly-detector"}, "WRONG_MODEL"),
    ],
)
def test_11_6_invalid_metadata_is_refused(
    run_dir: Path, changes: dict[str, Any], code: str
) -> None:
    rewrite_metadata(run_dir, **changes)
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == code


def test_11_4_hash_entries_cannot_point_outside_the_model_directory(
    run_dir: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    hashes = {
        "model.joblib": sha256_file(run_dir / "model.joblib"),
        "../secret.txt": sha256_file(outside),
    }
    rewrite_metadata(run_dir, artifact_sha256=hashes)
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "ARTIFACT_MISSING"


def test_11_5_missing_or_broken_files(tmp_path: Path, run_dir: Path) -> None:
    with pytest.raises(ModelLoadError) as exc:
        load(tmp_path / "nothing-here")
    assert exc.value.code == "METADATA_MISSING"
    (run_dir / "metadata.json").write_text("{not json")
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "METADATA_INVALID"
    (run_dir / "metadata.json").write_text("[1]")
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "METADATA_INVALID"


def test_11_5_a_valid_hash_over_garbage_is_still_refused(run_dir: Path) -> None:
    (run_dir / "model.joblib").write_bytes(b"not a pickle")
    rewrite_metadata(
        run_dir, artifact_sha256={"model.joblib": sha256_file(run_dir / "model.joblib")}
    )
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "ARTIFACT_INVALID"


def test_11_5_labels_inside_the_pickle_must_match_too(
    run_dir: Path, toy_artifacts: dict[str, Any]
) -> None:
    joblib.dump({**toy_artifacts, "labels": ["a", "b"]}, run_dir / "model.joblib")
    rewrite_metadata(
        run_dir, artifact_sha256={"model.joblib": sha256_file(run_dir / "model.joblib")}
    )
    with pytest.raises(ModelLoadError) as exc:
        load(run_dir)
    assert exc.value.code == "LABELS_MISMATCH"
