"""Data steps of the training flow (PRD 16.1 steps 1-4): load, validate, split check, parity.

Everything here is plain Python so it can be tested without Prefect. Failures raise
``PipelineError`` with a short code; messages never contain row contents (PRD 17.3).
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.errors as pa_errors
import pyarrow.parquet as pq

from ml.evaluation.splits import hash_frame
from ml.features import FEATURE_VERSION
from ml.features.classifier import (
    FEATURE_COLUMNS,
    build_feature_frame,
    online_features,
    row_to_input,
)
from ml.features.testing import assert_frames_parity
from ml.schemas.synthetic import validate_transactions

ASSIGNMENT_COLUMNS = ["transaction_id", "classifier_split", "anomaly_split"]


class PipelineError(RuntimeError):
    """A step failed in a way that must stop the pipeline (PRD 16.1 'fails pipeline when')."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class DatasetPaths:
    version: str
    data_dir: Path
    assignments: Path
    splits_json: Path


def dataset_paths(root: Path, version: str) -> DatasetPaths:
    """Convention: ``data/<version>``, ``data/splits/<version>``, ``data_splits/<version>``."""
    if not version or ".." in version.split("/") or version.startswith("/"):
        raise PipelineError("DATASET_INVALID", "dataset version must be a relative name")
    return DatasetPaths(
        version=version,
        data_dir=root / "data" / version,
        assignments=root / "data" / "splits" / version / "assignments.parquet",
        splits_json=root / "data_splits" / version / "splits.json",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(paths: DatasetPaths) -> dict[str, Any]:
    """Step 1: every file listed in the manifest must hash to the recorded value."""
    manifest_path = paths.data_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PipelineError("MANIFEST_MISSING", f"no manifest.json in {paths.data_dir}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name in ("transactions.parquet", "users.parquet"):
        expected = manifest.get("files_sha256", {}).get(name)
        target = paths.data_dir / name
        if expected is None or not target.is_file():
            raise PipelineError("MANIFEST_INCOMPLETE", f"{name} is not listed or not on disk")
        if sha256_file(target) != expected:
            raise PipelineError("HASH_MISMATCH", f"{name} does not match the manifest")
    return manifest


@dataclass(frozen=True)
class ValidationResult:
    rows: int
    quarantined: int
    quarantine_path: Path | None

    @property
    def quarantine_share(self) -> float:
        return self.quarantined / self.rows if self.rows else 0.0


def validate_dataset(
    paths: DatasetPaths, max_quarantine_share: float, batch_rows: int, quarantine_dir: Path
) -> ValidationResult:
    """Step 2: Pandera schema on every row, in batches.

    Rows that fail a row-level check go to a quarantine file that holds only ids and the failed
    check (never descriptions). Dataset-level failures and a quarantine share above the limit
    stop the pipeline.
    """
    quarantined: list[dict[str, str]] = []
    rows = 0
    pf = pq.ParquetFile(paths.data_dir / "transactions.parquet")
    for batch in pf.iter_batches(batch_size=batch_rows):
        frame = batch.to_pandas()
        rows += len(frame)
        try:
            validate_transactions(frame)
        except pa_errors.SchemaErrors as exc:
            cases = exc.failure_cases
            row_level = cases[cases["index"].notna()]
            if len(row_level) < len(cases):
                raise PipelineError("SCHEMA_VIOLATION", "a dataset-level check failed") from exc
            for index, check in zip(row_level["index"], row_level["check"], strict=True):
                quarantined.append(
                    {
                        "transaction_id": str(frame["transaction_id"].iloc[int(index)]),
                        "check": str(check),
                    }
                )
    unique = {q["transaction_id"] for q in quarantined}
    path: Path | None = None
    if quarantined:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        path = quarantine_dir / f"{paths.version.replace('/', '_')}.json"
        path.write_text(json.dumps(quarantined, indent=2), encoding="utf-8")
    result = ValidationResult(rows=rows, quarantined=len(unique), quarantine_path=path)
    if result.quarantine_share > max_quarantine_share:
        raise PipelineError(
            "QUARANTINE_TOO_LARGE",
            f"{result.quarantined} of {rows} rows fail validation "
            f"(limit {max_quarantine_share:.2%})",
        )
    return result


def verify_splits(paths: DatasetPaths) -> dict[str, str]:
    """Step 3: the locked assignments must hash to the committed split hash."""
    if not paths.splits_json.is_file():
        raise PipelineError("SPLITS_MISSING", f"no splits.json for {paths.version}")
    committed = json.loads(paths.splits_json.read_text(encoding="utf-8"))
    assignments = pd.read_parquet(paths.assignments, columns=ASSIGNMENT_COLUMNS)
    if hash_frame(assignments) != committed["hashes"]["assignments"]:
        raise PipelineError("SPLIT_HASH_MISMATCH", "assignments differ from the locked splits")
    transactions_sha = sha256_file(paths.data_dir / "transactions.parquet")
    if transactions_sha != committed["dataset"]["transactions_parquet_sha256"]:
        raise PipelineError("SPLIT_DATASET_MISMATCH", "splits were made for another dataset")
    return {
        "split_hash": str(committed["hashes"]["split_hash"]),
        "feature_version": FEATURE_VERSION,
    }


def feature_parity_sample(
    paths: DatasetPaths, sample_rows: int, seed: int, tolerance: float = 1e-6
) -> int:
    """Step 4: batch features must equal the serving-path features on a seeded sample.

    The classifier features are per row (no history), so the point-in-time risk is replaced by
    the batch/online parity that the PRD requires (11.1). Raises when they differ.
    """
    pf = pq.ParquetFile(paths.data_dir / "transactions.parquet")
    total = pf.metadata.num_rows
    fraction = min(1.0, sample_rows / max(total, 1))
    rng = random.Random(seed)
    parts: list[pd.DataFrame] = []
    for part in pf.iter_batches(
        batch_size=200_000,
        columns=["description", "merchant", "amount", "type", "payment_method", "date"],
    ):
        frame = part.to_pandas()
        keep = [i for i in range(len(frame)) if rng.random() < fraction]
        parts.append(frame.iloc[keep])
    sample = pd.concat(parts, ignore_index=True)
    batch = build_feature_frame(sample)
    online = pd.DataFrame(
        [online_features(row_to_input(row)) for _, row in sample.iterrows()],
        columns=list(FEATURE_COLUMNS),
    )
    try:
        assert_frames_parity(batch[list(FEATURE_COLUMNS)], online, tolerance)
    except AssertionError as exc:
        raise PipelineError("FEATURE_PARITY", str(exc)) from exc
    return len(sample)
