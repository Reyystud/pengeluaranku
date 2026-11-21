"""Promote and rollback on a throw-away MLflow registry (PRD 16.3, 16.5; T-27)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from mlflow.tracking import MlflowClient

from pipelines import promotion
from pipelines.__main__ import main
from pipelines.data_steps import PipelineError

MODEL = "transaction-classifier"


@pytest.fixture
def registry(tmp_path: Path) -> tuple[MlflowClient, str]:
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    client = MlflowClient(uri, uri)
    client.create_registered_model(MODEL)
    for gate in ("passed", "passed", "needs_review", None):
        tags = {"gate": gate} if gate else {}
        client.create_model_version(MODEL, source="runs:/x/model", tags=tags)
    return client, uri


def alias(client: MlflowClient, name: str) -> str | None:
    try:
        return str(client.get_model_version_by_alias(MODEL, name).version)
    except Exception:
        return None


def test_fr_16_05_first_promotion_sets_production_without_previous(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    client.set_registered_model_alias(MODEL, "candidate", "1")
    log = tmp_path / "ops" / "log.md"
    change = promotion.promote(client, MODEL, "1", log_path=log)
    assert (change.from_version, change.to_version) == (None, "1")
    assert alias(client, "production") == "1" and alias(client, "previous") is None
    assert alias(client, "candidate") is None  # promoted candidates stop being candidates
    assert "| promote | transaction-classifier | - | 1 |" in log.read_text()


def test_fr_16_05_promote_parks_old_production_as_previous(
    registry: tuple[MlflowClient, str],
) -> None:
    client, _ = registry
    promotion.promote(client, MODEL, "1", log_path=None)
    promotion.promote(client, MODEL, "2", log_path=None)
    assert alias(client, "production") == "2" and alias(client, "previous") == "1"
    assert client.get_model_version(MODEL, "2").tags["promote_from"] == "1"


def test_fr_16_03_promote_refuses_unpassed_versions_unless_forced_with_reason(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    for version in ("3", "4"):  # needs_review, and a version with no gate tag at all
        with pytest.raises(PipelineError, match="GATE_NOT_PASSED"):
            promotion.promote(client, MODEL, version, log_path=None)
    assert alias(client, "production") is None
    with pytest.raises(PipelineError, match="REASON_REQUIRED"):
        promotion.promote(client, MODEL, "3", force=True, log_path=None)
    log = tmp_path / "log.md"
    promotion.promote(client, MODEL, "3", force=True, reason="reviewed slices", log_path=log)
    assert alias(client, "production") == "3"
    assert client.get_model_version(MODEL, "3").tags["forced"] == "true"
    assert "forced: reviewed slices" in log.read_text()


def test_fr_16_05_promote_rejects_unknown_and_current_versions(
    registry: tuple[MlflowClient, str],
) -> None:
    client, _ = registry
    with pytest.raises(PipelineError, match="VERSION_NOT_FOUND"):
        promotion.promote(client, MODEL, "99", log_path=None)
    promotion.promote(client, MODEL, "1", log_path=None)
    with pytest.raises(PipelineError, match="ALREADY_PRODUCTION"):
        promotion.promote(client, MODEL, "1", log_path=None)


def test_fr_16_05_rollback_swaps_and_is_reversible_and_logged(
    registry: tuple[MlflowClient, str], tmp_path: Path
) -> None:
    client, _ = registry
    promotion.promote(client, MODEL, "1", log_path=None)
    promotion.promote(client, MODEL, "2", log_path=None)
    log = tmp_path / "log.md"
    promotion.rollback(client, MODEL, actor="me", reason="bad slice | in prod", log_path=log)
    assert alias(client, "production") == "1" and alias(client, "previous") == "2"
    assert client.get_model_version(MODEL, "2").tags["rolled_back_reason"] == "bad slice / in prod"
    promotion.rollback(client, MODEL, reason="undo", log_path=log)
    assert alias(client, "production") == "2" and alias(client, "previous") == "1"
    rows = [r for r in log.read_text().splitlines() if "| rollback |" in r]
    assert len(rows) == 2 and "| 2 | 1 | me | bad slice / in prod |" in rows[0]


def test_fr_16_05_rollback_needs_a_reason_and_a_previous_version(
    registry: tuple[MlflowClient, str],
) -> None:
    client, _ = registry
    with pytest.raises(PipelineError, match="REASON_REQUIRED"):
        promotion.rollback(client, MODEL, log_path=None)
    with pytest.raises(PipelineError, match="NO_PREVIOUS"):
        promotion.rollback(client, MODEL, reason="x", log_path=None)
    client.set_registered_model_alias(MODEL, "previous", "1")
    with pytest.raises(PipelineError, match="NO_PRODUCTION"):
        promotion.rollback(client, MODEL, reason="x", log_path=None)


def test_fr_16_05_cli_exit_codes(
    registry: tuple[MlflowClient, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, uri = registry
    monkeypatch.chdir(tmp_path)  # the default rollback log is relative to the repo root
    base = ["--tracking-uri", uri]
    assert main(["promote", "--version", "1", *base]) == 0
    assert main(["promote", "--version", "3", *base]) == 2
    assert main(["promote", "--version", "2", *base]) == 0
    assert main(["rollback", *base]) == 2  # no reason
    assert main(["rollback", "--reason", "drill", *base]) == 0
    assert alias(client, "production") == "1"
    assert (tmp_path / "docs/ops/rollback-log.md").is_file()
