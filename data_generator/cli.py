"""Command line interface: ``python -m data_generator generate ...`` (PRD 10.1)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from data_generator.config import load_config
from data_generator.generate import write_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="data_generator")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="generate a synthetic dataset")
    gen.add_argument("--config", type=Path, required=True)
    gen.add_argument("--seed", type=int, required=True)
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument("--n-users", type=int, help="override n_users (recorded in manifest)")
    gen.add_argument("--months", type=int, help="override months (recorded in manifest)")
    gen.add_argument("--workers", type=int, default=1, help="processes (output is identical)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config, seed=args.seed, n_users=args.n_users, months=args.months)
    started = time.perf_counter()
    manifest = write_dataset(cfg, args.out, workers=args.workers)
    counts = manifest["row_counts"]
    print(
        f"generated {counts['transactions']:,} transactions for {counts['users']:,} users "
        f"in {time.perf_counter() - started:.1f}s -> {args.out}"
    )
    return 0
