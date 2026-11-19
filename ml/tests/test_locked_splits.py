"""Verifies the committed splits still match the locally generated default dataset.

Skipped when ``data/synthetic/v1`` is absent (it is gitignored; create it with ``make data``).
A failure here means the dataset or the split algorithm changed after the splits were locked,
which requires an ADR (PRD 10.4).
"""

from pathlib import Path

import pytest

from ml.evaluation.__main__ import _load
from ml.evaluation.splits import SplitParams, assert_no_leakage, compute_splits, verify_split_files

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "synthetic" / "v1"
SPLITS = ROOT / "data_splits" / "synthetic" / "v1"

pytestmark = pytest.mark.skipif(
    not (DATA / "manifest.json").exists() or not (SPLITS / "splits.json").exists(),
    reason="needs data/synthetic/v1 (make data) and committed data_splits/synthetic/v1",
)


def test_committed_splits_match_the_default_dataset() -> None:
    tx, users, _, start, end = _load(DATA)
    result = compute_splits(tx, users, start, end, SplitParams())
    assert verify_split_files(result, SPLITS) == []
    assert_no_leakage(result, tx)
