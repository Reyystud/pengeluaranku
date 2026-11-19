"""Orchestration: simulate all users, validate, write Parquet/CSV and manifest.json."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import subprocess
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from data_generator import GENERATOR_VERSION
from data_generator.config import GeneratorConfig
from data_generator.simulate import simulate_chunk
from ml.schemas.synthetic import (
    TRANSACTION_COLUMNS,
    USER_COLUMNS,
    validate_transactions,
    validate_users,
)
from ml.taxonomy import TAXONOMY_VERSION

_CENT = Decimal("0.01")
_CHUNK = 50

TRANSACTIONS_ARROW_SCHEMA = pa.schema(
    [
        ("date", pa.string()),
        ("description", pa.string()),
        ("amount", pa.decimal128(15, 2)),
        ("type", pa.string()),
        ("payment_method", pa.string()),
        ("merchant", pa.string()),
        ("category", pa.string()),
        ("notes", pa.string()),
        ("transaction_id", pa.string()),
        ("user_id", pa.string()),
        ("archetype", pa.string()),
        ("true_category", pa.string()),
        ("is_anomaly", pa.bool_()),
        ("anomaly_type", pa.string()),
        ("anomaly_severity", pa.string()),
        ("recurring_series_id", pa.string()),
        ("has_time", pa.bool_()),
    ]
)
USERS_ARROW_SCHEMA = pa.schema(
    [
        ("user_id", pa.string()),
        ("archetype", pa.string()),
        ("income_profile", pa.string()),
        ("budget_period_start_day", pa.int32()),
        ("created_at", pa.timestamp("us", tz="UTC")),
    ]
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": "unknown", "dirty": None}


def _simulate_frames(
    cfg: GeneratorConfig, assignments: list[str], indices: list[int]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate a chunk of users and return plain frames (keeps worker->parent payloads small)."""
    rows, users = simulate_chunk(cfg, assignments, indices)
    return (
        pd.DataFrame(rows, columns=list(TRANSACTION_COLUMNS)),
        pd.DataFrame(users, columns=list(USER_COLUMNS)),
    )


def build_frames(cfg: GeneratorConfig, workers: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate every user and return validated (transactions, users) frames."""
    assignments = cfg.assign_archetypes()
    chunks = [list(range(i, min(i + _CHUNK, cfg.n_users))) for i in range(0, cfg.n_users, _CHUNK)]
    if workers > 1:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool:
            results = list(
                pool.map(
                    _simulate_frames,
                    [cfg] * len(chunks),
                    [assignments] * len(chunks),
                    chunks,
                )
            )
    else:
        results = [_simulate_frames(cfg, assignments, c) for c in chunks]

    transactions = pd.concat([t for t, _ in results], ignore_index=True)
    transactions["amount"] = transactions["amount"].map(lambda v: Decimal(int(v)).quantize(_CENT))
    users = pd.concat([u for _, u in results], ignore_index=True)
    users["created_at"] = (
        pd.to_datetime(users["created_at"]).dt.tz_localize("UTC").astype("datetime64[us, UTC]")
    )
    users["budget_period_start_day"] = users["budget_period_start_day"].astype("int64")

    # Self-validation (PRD 10.1): the generator fails on any schema violation.
    return validate_transactions(transactions), validate_users(users)


def write_dataset(cfg: GeneratorConfig, out_dir: Path, workers: int = 1) -> dict[str, Any]:
    """Generate the dataset into ``out_dir`` and return the manifest."""
    transactions, users = build_frames(cfg, workers)
    out_dir.mkdir(parents=True, exist_ok=True)

    tx_parquet, tx_csv = out_dir / "transactions.parquet", out_dir / "transactions.csv"
    users_parquet = out_dir / "users.parquet"
    pq.write_table(
        pa.Table.from_pandas(transactions, schema=TRANSACTIONS_ARROW_SCHEMA, preserve_index=False),
        tx_parquet,
        compression="zstd",
    )
    transactions.to_csv(tx_csv, index=False, lineterminator="\n", na_rep="")
    pq.write_table(
        pa.Table.from_pandas(users, schema=USERS_ARROW_SCHEMA, preserve_index=False),
        users_parquet,
        compression="zstd",
    )

    manifest: dict[str, Any] = {
        "generator_version": GENERATOR_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "dataset_name": cfg.dataset_name,
        "git": _git_state(),
        "seed": cfg.seed,
        "config": cfg.manifest_config(),
        "row_counts": {
            "users": len(users),
            "transactions": len(transactions),
            "by_type": {k: int(v) for k, v in transactions["type"].value_counts().items()},
            "anomaly_rows": int(transactions["is_anomaly"].sum()),
            "recurring_rows": int(transactions["recurring_series_id"].notna().sum()),
            "date_only_rows": int((~transactions["has_time"]).sum()),
        },
        "files_sha256": {p.name: _sha256(p) for p in (tx_parquet, tx_csv, users_parquet)},
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest
