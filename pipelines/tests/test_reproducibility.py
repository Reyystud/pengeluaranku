"""Decision logic of the re-run check (PRD 16.2). The real two-process run is `make repro`."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipelines import reproducibility as repro


def summary(f1: float, split: str = "s", data: str = "d") -> repro.RunSummary:
    return repro.RunSummary(macro_f1=f1, winner="logreg", split_hash=split, dataset_sha256=data)


def fake(monkeypatch: pytest.MonkeyPatch, runs: list[repro.RunSummary]) -> None:
    monkeypatch.setattr(repro, "build_dataset", lambda root, cfg: None)
    queue = iter(runs)
    monkeypatch.setattr(repro, "_child", lambda root, work: next(queue))


def test_fr_16_02_identical_runs_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, [summary(0.9), summary(0.9)])
    result = repro.check()
    assert result["passed"] and result["macro_f1_delta"] == 0.0


def test_fr_16_02_delta_boundary_is_inclusive_and_above_it_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake(monkeypatch, [summary(0.90), summary(0.91)])
    assert repro.check(max_delta=0.0100000001)["passed"]
    fake(monkeypatch, [summary(0.90), summary(0.9101)])
    result = repro.check()
    assert not result["passed"] and "macro F1 differs" in result["problems"][0]


def test_fr_16_02_different_data_or_splits_fail_even_with_equal_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake(monkeypatch, [summary(0.9, split="a"), summary(0.9, split="b")])
    assert not repro.check()["passed"]
    fake(monkeypatch, [summary(0.9, data="a"), summary(0.9, data="b")])
    assert not repro.check()["passed"]


def test_fr_16_02_main_writes_the_result_and_sets_the_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake(monkeypatch, [summary(0.9), summary(0.5)])
    out = tmp_path / "r.json"
    assert repro.main(["--out", str(out)]) == 1
    assert '"passed": false' in out.read_text()
