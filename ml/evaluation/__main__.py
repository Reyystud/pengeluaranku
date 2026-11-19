"""``python -m ml.evaluation make-splits`` / ``verify-splits`` (PRD 10.4)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from ml.evaluation.splits import (
    SplitParams,
    assert_no_leakage,
    compute_splits,
    verify_split_files,
    write_split_files,
)


def _load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], date, date]:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    params = manifest["config"]["params"]
    start = date.fromisoformat(str(params["start_date"]))
    months = int(params["months"])
    index = start.month - 1 + months
    end = date(start.year + index // 12, index % 12 + 1, 1)
    tx = pd.read_parquet(
        data_dir / "transactions.parquet",
        columns=["transaction_id", "user_id", "date", "true_merchant", "true_category"],
    )
    users = pd.read_parquet(data_dir / "users.parquet")
    return tx, users, manifest, start, end


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ml.evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("make-splits", "verify-splits"):
        p = sub.add_parser(name)
        p.add_argument("--data", type=Path, required=True, help="dataset dir (with manifest.json)")
        p.add_argument("--dataset-version", required=True, help="e.g. synthetic/v1")
        p.add_argument("--splits-dir", type=Path, default=Path("data_splits"))
        if name == "make-splits":
            p.add_argument("--assignments-dir", type=Path, default=Path("data/splits"))
            p.add_argument(
                "--force", action="store_true", help="overwrite locked splits (requires an ADR)"
            )
    args = parser.parse_args(argv)

    tx, users, manifest, start, end = _load(args.data)
    result = compute_splits(tx, users, start, end, SplitParams())
    committed = args.splits_dir / args.dataset_version

    if args.command == "make-splits":
        assert_no_leakage(result, tx)
        if (committed / "splits.json").exists() and not args.force:
            problems = verify_split_files(result, committed)
            if problems:
                print(
                    "Splits are locked and would change (needs an ADR, then --force):\n  "
                    + "\n  ".join(problems)
                )
                return 1
        info = {
            "dataset_version": args.dataset_version,
            "generator_version": manifest["generator_version"],
            "seed": manifest["seed"],
            "transactions_parquet_sha256": manifest["files_sha256"]["transactions.parquet"],
        }
        summary = write_split_files(
            result, committed, info, args.assignments_dir / args.dataset_version
        )
        print(f"wrote {committed}  split_hash={summary['hashes']['split_hash']}")
        return 0

    problems = verify_split_files(result, committed)
    if problems:
        print("SPLITS CHANGED:\n  " + "\n  ".join(problems))
        return 1
    print(f"splits verified: {result.hashes()['split_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
