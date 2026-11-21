"""Tests for the train_model flow on a tiny dataset (PRD 16.1, 16.3; T-25)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from mlflow.tracking import MlflowClient

from ml.classification.config import load_train_config
from pipelines import train_flow
from pipelines.data_steps import PipelineError
from pipelines.tests.conftest import VERSION


@pytest.fixture
def clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(train_flow, "git_state", lambda root: ("abc1234", False))


@pytest.fixture
def dirty_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(train_flow, "git_state", lambda root: ("abc1234", True))


@pytest.fixture
def relaxed_config(tmp_path: Path) -> str:
    """The tiny dataset is too small to meet the ECE gate; the gate itself has its own test."""
    cfg = load_train_config()
    cfg["gates"]["max_ece"] = 1.0
    cfg["behavioural"].update(
        golden_min_accuracy=0.0, min_correct_share_per_category=0.0, invariance_min_pass_rate=0.0
    )
    path = tmp_path / "classifier.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return str(path)


def run_flow(root: Path, tmp_path: Path, config: str | None = None, **kw: Any) -> Any:
    return train_flow.run_training(
        "transaction-classifier",
        VERSION,
        models=["logreg"],
        max_rows_per_class=200,
        config_path=config,
        root=str(root),
        mlflow_dir=str(tmp_path / "mlflow"),
        **kw,
    )


def test_fr_16_01_clean_run_registers_candidate_with_complete_metadata(
    tiny_root: Path, tmp_path: Path, clean_tree: None, relaxed_config: str
) -> None:
    result = run_flow(tiny_root, tmp_path, relaxed_config)
    assert result.gate == "passed"
    assert result.registered_version == "1"
    client = MlflowClient(f"sqlite:///{tmp_path / 'mlflow' / 'mlflow.db'}")
    version = client.get_model_version_by_alias("transaction-classifier", "candidate")
    assert str(version.version) == "1"
    assert version.tags["gate"] == "passed"
    meta = json.loads((result.run_dir / "metadata.json").read_text())
    assert meta["mlflow_version"] == "1"
    assert meta["semantic_version"] == "0.1.0"
    assert meta["dataset"]["split_hash"] and meta["dataset"]["transactions_sha256"]
    assert meta["metrics"]["macro_f1_test"] == pytest.approx(result.test_macro_f1)
    assert {"python", "scikit-learn"} <= set(meta["runtime"])
    statuses = {g["name"]: g["status"] for g in meta["gates"]}
    assert statuses["behavioural_tests"] == "pass" and statuses["latency"] == "pass"
    assert statuses["beats_production"] == "skipped"  # nothing to compare with yet
    assert 0.0 <= meta["metrics"]["golden_accuracy"] <= 1.0
    assert meta["metrics"]["latency_p95_ms"] > 0
    report = json.loads((result.run_dir / "evaluation" / "report.json").read_text())
    assert report["behavioural"]["n_cases"] >= 100
    assert report["latency_benchmark"]["requests"] == 1000
    assert report["latency_benchmark"]["threads"] == 2
    # the logged artifact carries the same metadata and a generated model card
    local = client.download_artifacts(version.run_id, "model/metadata.json", str(tmp_path / "dl"))
    assert json.loads(Path(local).read_text())["mlflow_version"] == "1"
    card = client.download_artifacts(version.run_id, "model/model_card.md", str(tmp_path / "dl"))
    text = Path(card).read_text()
    assert "registry version `1`" in text and "Synthetic data only" in text


def test_fr_16_01_parent_run_has_one_child_per_candidate(
    tiny_root: Path, tmp_path: Path, clean_tree: None, relaxed_config: str
) -> None:
    result = run_flow(tiny_root, tmp_path, relaxed_config, register=False)
    client = MlflowClient(f"sqlite:///{tmp_path / 'mlflow' / 'mlflow.db'}")
    run = client.get_run(result.mlflow_run_id)
    assert run.data.tags["dirty"] == "false" and run.data.tags["gate"] == "passed"
    assert run.data.params["split_hash"] and run.data.params["git_commit"] == "abc1234"
    exp = client.get_experiment_by_name("classifier")
    assert exp is not None
    children = client.search_runs(
        [exp.experiment_id], filter_string=f"tags.mlflow.parentRunId = '{result.mlflow_run_id}'"
    )
    assert [c.data.params["model"] for c in children] == ["logreg"]
    assert result.registered_version is None  # register=False
    artifacts = {a.path for a in client.list_artifacts(result.mlflow_run_id)}
    assert {"environment", "gates.json", "summary.md", "model"} <= artifacts


def test_fr_16_01_dirty_tree_is_logged_but_never_registered(
    tiny_root: Path, tmp_path: Path, dirty_tree: None, relaxed_config: str
) -> None:
    result = run_flow(tiny_root, tmp_path, relaxed_config)
    assert result.gate == "failed" and result.registered_version is None
    repro = next(g for g in result.gates if g.name == "reproducibility")
    assert repro.status == "fail"
    client = MlflowClient(f"sqlite:///{tmp_path / 'mlflow' / 'mlflow.db'}")
    run = client.get_run(result.mlflow_run_id)
    assert run.data.tags["dirty"] == "true" and run.data.tags["gate"] == "failed"
    assert client.search_registered_models() == []


def test_fr_16_03_failed_calibration_gate_blocks_registration(
    tiny_root: Path, tmp_path: Path, clean_tree: None
) -> None:
    cfg = load_train_config()
    cfg["gates"]["max_ece"] = 0.0  # no real model has an ECE of exactly zero
    path = tmp_path / "strict.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    result = run_flow(tiny_root, tmp_path, str(path))
    assert result.gate == "failed" and result.registered_version is None
    assert next(g for g in result.gates if g.name == "calibration").status == "fail"


def test_fr_16_01_unknown_model_is_rejected(tiny_root: Path, tmp_path: Path) -> None:
    with pytest.raises(PipelineError, match="MODEL_UNSUPPORTED"):
        train_flow.run_training("expense-forecaster", VERSION, root=str(tiny_root))


def test_fr_16_01_second_registration_moves_candidate_alias(
    tiny_root: Path, tmp_path: Path, clean_tree: None, relaxed_config: str
) -> None:
    run_flow(tiny_root, tmp_path, relaxed_config)
    second = run_flow(tiny_root, tmp_path, relaxed_config)
    assert second.registered_version == "2"
    client = MlflowClient(f"sqlite:///{tmp_path / 'mlflow' / 'mlflow.db'}")
    assert (
        str(client.get_model_version_by_alias("transaction-classifier", "candidate").version) == "2"
    )
    # promotion is T-27: the flow must never create `production`
    with pytest.raises(Exception, match="not found|alias"):
        client.get_model_version_by_alias("transaction-classifier", "production")


def test_fr_21_04_default_behavioural_thresholds_block_a_weak_model(
    tiny_root: Path, tmp_path: Path, clean_tree: None
) -> None:
    """A model trained on 4 months of 60 users cannot reach the golden-set accuracy."""
    cfg = load_train_config()
    cfg["gates"]["max_ece"] = 1.0  # isolate the behavioural gate
    path = tmp_path / "default_beh.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    result = run_flow(tiny_root, tmp_path, str(path))
    gate = next(g for g in result.gates if g.name == "behavioural_tests")
    assert gate.status == "fail" and "golden_accuracy" in gate.detail
    assert result.gate == "failed" and result.registered_version is None


def test_fr_16_03_production_alias_is_the_reference_for_the_next_run(
    tiny_root: Path, tmp_path: Path, clean_tree: None, relaxed_config: str
) -> None:
    first = run_flow(tiny_root, tmp_path, relaxed_config)
    client = MlflowClient(f"sqlite:///{tmp_path / 'mlflow' / 'mlflow.db'}")
    client.set_registered_model_alias(
        "transaction-classifier", "production", first.registered_version
    )
    second = run_flow(tiny_root, tmp_path, relaxed_config)  # identical model: no +0.5 point gain
    gate = next(g for g in second.gates if g.name == "beats_production")
    assert gate.status == "fail" and "production v1" in gate.detail
    assert second.gate == "failed" and second.registered_version is None
    # the production alias was neither moved nor removed by the flow
    prod = client.get_model_version_by_alias("transaction-classifier", "production")
    assert str(prod.version) == "1"
