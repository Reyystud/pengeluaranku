"""Load the synthetic dataset for model experiments (PRD 10.4): sampled users, parsed times."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd


def sample_users(user_ids: list[str], n: int, salt: str) -> list[str]:
    """First ``n`` users in SHA-256 order: deterministic, no RNG (same rule as the splits)."""
    ordered = sorted(user_ids, key=lambda u: hashlib.sha256(f"{salt}:{u}".encode()).hexdigest())
    return sorted(ordered[:n])


def load_transactions(data_dir: Path, users: list[str] | None = None) -> pd.DataFrame:
    """Rows of ``users`` (all when None) with ``occurred_at`` (datetime), float ``amount_f``,
    ``category`` = the generator's true category and ``merchant_key`` = its lower-cased merchant."""
    tx = pd.read_parquet(data_dir / "transactions.parquet")
    if users is not None:
        tx = tx[tx["user_id"].isin(users)]
    tx = tx.copy()
    tx["occurred_at"] = pd.to_datetime(tx["date"].astype(str), format="mixed")
    tx["amount_f"] = tx["amount"].astype(float)
    tx["category"] = tx["true_category"]
    tx["merchant_key"] = tx["true_merchant"].astype(str).str.lower()
    return tx.sort_values(["user_id", "occurred_at", "transaction_id"], kind="stable").reset_index(
        drop=True
    )
