"""Measure the recurring detector against the generator's ground truth (PRD 7.8, 9.5).

The synthetic dataset labels subscription and monthly-bill rows with ``recurring_series_id``.
Habit merchants and income are not labelled, so they cannot be scored: precision is computed over
expense series only and income detections are reported as a separate count. Everything printed is
a count or a ratio; no descriptions or merchants leave this module.

    uv run python -m ml.recurring.evaluate --users 1000 --out data/recurring_eval.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from ml.preprocessing.merchant import resolve_merchant
from ml.recurring import Occurrence, detect, load_recurring_config


def evaluate_user(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = load_recurring_config()
    occurrences: list[Occurrence] = []
    series_of: dict[str, str | None] = {}
    last_day = date.min
    for i, r in enumerate(rows):
        day = date.fromisoformat(str(r["date"])[:10])
        last_day = max(last_day, day)
        merchant = r.get("merchant")
        display, key = resolve_merchant(
            merchant if isinstance(merchant, str) else None, str(r["description"])
        )
        tid = str(i)
        series_of[tid] = (
            r["recurring_series_id"] if isinstance(r["recurring_series_id"], str) else None
        )
        occurrences.append(
            Occurrence(
                tid,
                key,
                display,
                str(r["type"]),
                "",
                day,
                Decimal(str(r["amount"])),
            )
        )
    found = detect(occurrences, last_day, cfg)

    by_gt: dict[str, set[date]] = defaultdict(set)
    for occ in occurrences:
        sid = series_of[occ.transaction_id]
        if sid and occ.transaction_type == "expense":
            by_gt[sid].add(occ.day)
    detectable = {sid for sid, days in by_gt.items() if len(days) >= cfg.min_occurrences}

    matched: set[str] = set()
    true_pos = false_pos = income = 0
    frequencies: Counter[str] = Counter()
    for s in found:
        frequencies[f"{s.transaction_type}:{s.frequency}"] += 1
        if s.transaction_type == "income":
            income += 1
            continue
        votes = Counter(series_of[tid] for tid in s.transaction_ids)
        top, hits = votes.most_common(1)[0]
        if top is not None and hits / len(s.transaction_ids) > 0.5:
            true_pos += 1
            matched.add(top)
        else:
            false_pos += 1
    return {
        "detected_expense": true_pos + false_pos,
        "true_positive": true_pos,
        "false_positive": false_pos,
        "income_detected": income,
        "ground_truth": len(detectable),
        "recalled": len(matched & detectable),
        "frequencies": dict(frequencies),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ml.recurring.evaluate")
    parser.add_argument("--data", default="data/synthetic/v1")
    parser.add_argument("--users", type=int, default=1000, help="random user sample (0 = all)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    frame = pd.read_parquet(
        Path(args.data) / "transactions.parquet",
        columns=[
            "user_id",
            "date",
            "description",
            "merchant",
            "amount",
            "type",
            "category",
            "recurring_series_id",
        ],
    )
    users = sorted(frame["user_id"].unique())
    if args.users and args.users < len(users):
        users = random.Random(args.seed).sample(users, args.users)
    wanted = set(users)
    totals: Counter[str] = Counter()
    frequencies: Counter[str] = Counter()
    for _, group in frame[frame["user_id"].isin(wanted)].groupby("user_id", sort=False):
        result = evaluate_user(list(group.to_dict("records")))  # type: ignore[arg-type]
        frequencies.update(result.pop("frequencies"))
        totals.update(result)
    precision = (
        totals["true_positive"] / totals["detected_expense"] if totals["detected_expense"] else None
    )
    recall = totals["recalled"] / totals["ground_truth"] if totals["ground_truth"] else None
    report = {
        "config_version": load_recurring_config().version,
        "dataset": str(args.data),
        "users": len(users),
        "seed": args.seed,
        **dict(totals),
        "expense_precision": precision,
        "recall": recall,
        "detected_by_frequency": dict(sorted(frequencies.items())),
        "note": "precision/recall on expense series only; habit merchants are not labelled in the "
        "generator, so some false positives may be real habits",
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
