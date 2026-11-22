"""Prediction and shadow-error lines out of captured ml-service output (PRD 18.4, 16.4).

Locally the lines come from ``docker compose logs ml-service``; in GCP they would come from the
BigQuery view over the Log Router table (not wired: the same columns, a different reader).
Lines that are not JSON, or not ``prediction`` / ``shadow_error`` events, are skipped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

PREDICTION_COLUMNS = (
    "logged_at",
    "request_id",
    "input_hash",
    "model_version",
    "predicted_category",
    "confidence",
    "latency_ms",
    "shadow",
)
ERROR_COLUMNS = ("logged_at", "request_id", "model_version", "error_type")


def parse_lines(lines: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(predictions of production and shadow, shadow errors)."""
    preds: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            doc = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        try:
            if doc.get("event") == "prediction":
                preds.append(
                    {
                        "logged_at": pd.Timestamp(doc["logged_at"]),
                        "request_id": str(doc["request_id"]),
                        "input_hash": str(doc["input_hash"]),
                        "model_version": str(doc["model_version"]),
                        "predicted_category": str(doc["output"]["predicted_category"]),
                        "confidence": float(doc["output"]["confidence"]),
                        "latency_ms": float(doc["latency_ms"]),
                        "shadow": bool(doc.get("shadow")),
                    }
                )
            elif doc.get("event") == "shadow_error":
                errors.append(
                    {
                        "logged_at": pd.Timestamp(doc["logged_at"]),
                        "request_id": str(doc["request_id"]),
                        "model_version": str(doc["model_version"]),
                        "error_type": str(doc.get("error_type", "")),
                    }
                )
        except (KeyError, TypeError, ValueError):
            continue
    return _frame(preds, PREDICTION_COLUMNS), _frame(errors, ERROR_COLUMNS)


def _frame(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(columns))
    frame["logged_at"] = pd.to_datetime(frame["logged_at"], utc=True)
    return frame


def read_files(paths: Iterable[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    lines: list[str] = []
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as handle:
            lines.extend(handle)
    return parse_lines(lines)


def read_corrections(path: Path) -> dict[str, str]:
    """``input_hash -> category the user corrected it to``, from a JSONL file.

    Keyed by the same 12-character hash the prediction lines carry, so no description or amount
    leaves the product database. In GCP this is the `category_labels` export (T-27 follow-up).
    """
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            doc = json.loads(line)
            out[str(doc["input_hash"])] = str(doc["category"])
    return out
