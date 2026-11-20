"""Load classifier datasets by split, computing features with the shared feature module."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ml.features.classifier import INPUT_COLUMNS, build_feature_frame

EXTRA_COLUMNS = ("true_category", "archetype", "true_merchant", "description")
SPLITS = ("train", "validation", "test", "test_unseen_merchant")
BATCH_ROWS = 200_000


def load_split_frames(data_dir: Path, assignments_path: Path) -> dict[str, pd.DataFrame]:
    """Return ``{split: frame}`` for the classifier splits.

    Each frame has the feature columns of ``build_feature_frame`` plus ``label`` (true category),
    ``archetype``, ``true_merchant`` and ``description`` (the last three for slices and error
    analysis only; they are never model inputs). Read in batches to bound memory.
    """
    assign = pd.read_parquet(assignments_path, columns=["transaction_id", "classifier_split"])
    split_of = assign.set_index("transaction_id")["classifier_split"]
    columns = [*INPUT_COLUMNS, "transaction_id", *EXTRA_COLUMNS]
    columns = list(dict.fromkeys(columns))
    parts: dict[str, list[pd.DataFrame]] = {s: [] for s in SPLITS}
    pf = pq.ParquetFile(data_dir / "transactions.parquet")
    for batch in pf.iter_batches(batch_size=BATCH_ROWS, columns=columns):
        df = batch.to_pandas()
        df["split"] = df["transaction_id"].map(split_of)
        feats = build_feature_frame(df)
        feats["label"] = df["true_category"].to_numpy()
        feats["archetype"] = df["archetype"].to_numpy()
        feats["true_merchant"] = df["true_merchant"].to_numpy()
        feats["description"] = df["description"].to_numpy()
        for name in SPLITS:
            mask = (df["split"] == name).to_numpy()
            if mask.any():
                parts[name].append(feats[mask])
    return {name: pd.concat(chunks, ignore_index=True) for name, chunks in parts.items()}


def cap_per_class(frame: pd.DataFrame, max_rows: int, seed: int) -> pd.DataFrame:
    """Keep at most ``max_rows`` rows per label (deterministic given ``seed``)."""
    rng = np.random.default_rng(seed)
    keep: list[np.ndarray] = []
    for _, idx in frame.groupby("label").indices.items():
        values = np.asarray(idx)
        keep.append(
            values if len(values) <= max_rows else rng.choice(values, size=max_rows, replace=False)
        )
    chosen = np.sort(np.concatenate(keep))
    return frame.iloc[chosen].reset_index(drop=True)
