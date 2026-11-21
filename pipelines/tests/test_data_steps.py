"""Failure paths of the data steps (PRD 16.1 steps 1-4): each must stop the pipeline."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipelines import data_steps
from pipelines.data_steps import PipelineError
from pipelines.tests.conftest import VERSION


@pytest.fixture
def copy_root(tiny_root: Path, tmp_path: Path) -> Path:
    """A private copy of the tiny dataset that a test may corrupt."""
    target = tmp_path / "root"
    shutil.copytree(tiny_root / "data", target / "data")
    shutil.copytree(tiny_root / "data_splits", target / "data_splits")
    return target


def test_fr_16_01_clean_dataset_passes_every_data_step(tiny_root: Path, tmp_path: Path) -> None:
    paths = data_steps.dataset_paths(tiny_root, VERSION)
    assert data_steps.verify_manifest(paths)["row_counts"]["transactions"] > 0
    result = data_steps.validate_dataset(paths, 0.01, 5_000, tmp_path / "q")
    assert result.rows > 0 and result.quarantined == 0 and result.quarantine_path is None
    assert data_steps.verify_splits(paths)["split_hash"]
    assert data_steps.feature_parity_sample(paths, 100, seed=1) > 0


def test_fr_16_01_hash_mismatch_fails_the_pipeline(copy_root: Path) -> None:
    paths = data_steps.dataset_paths(copy_root, VERSION)
    with (paths.data_dir / "users.parquet").open("ab") as fh:
        fh.write(b"tamper")
    with pytest.raises(PipelineError, match="HASH_MISMATCH"):
        data_steps.verify_manifest(paths)


def test_fr_16_01_missing_manifest_fails(copy_root: Path) -> None:
    paths = data_steps.dataset_paths(copy_root, VERSION)
    (paths.data_dir / "manifest.json").unlink()
    with pytest.raises(PipelineError, match="MANIFEST_MISSING"):
        data_steps.verify_manifest(paths)


def test_fr_16_01_split_hash_mismatch_fails(copy_root: Path) -> None:
    paths = data_steps.dataset_paths(copy_root, VERSION)
    frame = pd.read_parquet(paths.assignments)
    frame.loc[frame.index[0], "classifier_split"] = "moved"  # a value no split uses
    frame.to_parquet(paths.assignments, index=False)
    with pytest.raises(PipelineError, match="SPLIT_HASH_MISMATCH"):
        data_steps.verify_splits(paths)


def test_fr_16_01_dataset_version_must_be_a_relative_name(tiny_root: Path) -> None:
    for bad in ("", "../x", "/etc"):
        with pytest.raises(PipelineError, match="DATASET_INVALID"):
            data_steps.dataset_paths(tiny_root, bad)


def _break_rows(paths: data_steps.DatasetPaths, count: int) -> None:
    table = pq.read_table(paths.data_dir / "transactions.parquet")
    frame = table.to_pandas()
    frame.loc[frame.index[:count], "type"] = "bogus"  # row-level check: type must be known
    pq.write_table(
        pa.Table.from_pandas(frame, schema=table.schema, preserve_index=False),
        paths.data_dir / "transactions.parquet",
    )


def test_fr_16_01_few_bad_rows_are_quarantined_without_content(
    copy_root: Path, tmp_path: Path
) -> None:
    paths = data_steps.dataset_paths(copy_root, VERSION)
    _break_rows(paths, 3)
    result = data_steps.validate_dataset(paths, 0.01, 5_000, tmp_path / "q")
    assert result.quarantined == 3 and result.quarantine_path is not None
    saved = json.loads(result.quarantine_path.read_text())
    assert {k for row in saved for k in row} == {"transaction_id", "check"}  # ids only (PRD 17.3)


def test_fr_16_01_quarantine_above_one_percent_fails(copy_root: Path, tmp_path: Path) -> None:
    paths = data_steps.dataset_paths(copy_root, VERSION)
    _break_rows(paths, 500)  # > 1% of the tiny dataset
    with pytest.raises(PipelineError, match="QUARANTINE_TOO_LARGE"):
        data_steps.validate_dataset(paths, 0.01, 5_000, tmp_path / "q")
