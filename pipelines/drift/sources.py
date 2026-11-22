"""Where the current window of prediction logs comes from (PRD 18.3, 18.4).

``JsonlLogSource`` reads captured stdout (local: ``docker compose logs ml-service``);
``BigQueryLogSource`` queries the view over the Log Router table (GCP). Both return the same
columns: ``logged_at`` (UTC), ``log_amount``, ``payment_method``, ``hour_bucket``,
``predicted_category``, ``confidence``, ``merchant_hash``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

import httpx
import pandas as pd

COLUMNS = (
    "logged_at",
    "log_amount",
    "payment_method",
    "hour_bucket",
    "predicted_category",
    "confidence",
    "merchant_hash",
)


class LogSource(Protocol):
    def fetch(self, since: dt.datetime, until: dt.datetime) -> pd.DataFrame:
        """Rows with ``since <= logged_at < until`` and the ``COLUMNS`` above."""


def parse_lines(lines: Iterable[str]) -> pd.DataFrame:
    """Prediction lines out of mixed log output: other lines, shadow predictions and bad JSON
    are ignored (a log file also holds request lines and tracebacks)."""
    rows: list[dict[str, Any]] = []
    for line in lines:
        start = line.find("{")
        if start < 0:
            continue
        try:
            doc = json.loads(line[start:])
        except ValueError:
            continue
        if not isinstance(doc, dict) or doc.get("event") != "prediction" or doc.get("shadow"):
            continue
        try:
            rows.append(
                {
                    "logged_at": pd.Timestamp(doc["logged_at"]),
                    "log_amount": float(doc["features_summary"]["log_amount"]),
                    "payment_method": doc["features_summary"]["payment_method"],
                    "hour_bucket": doc["features_summary"]["hour_bucket"],
                    "predicted_category": doc["output"]["predicted_category"],
                    "confidence": float(doc["output"]["confidence"]),
                    "merchant_hash": doc.get("merchant_hash"),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return _frame(rows)


def _frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(COLUMNS))
    frame["logged_at"] = pd.to_datetime(frame["logged_at"], utc=True)
    return frame


class JsonlLogSource:
    def __init__(self, paths: Iterable[Path]) -> None:
        self._paths = list(paths)

    def fetch(self, since: dt.datetime, until: dt.datetime) -> pd.DataFrame:
        frames = []
        for path in self._paths:
            with path.open(encoding="utf-8", errors="replace") as handle:
                frames.append(parse_lines(handle))
        frame = pd.concat(frames, ignore_index=True) if frames else _frame([])
        mask = (frame["logged_at"] >= since) & (frame["logged_at"] < until)
        return frame[mask].reset_index(drop=True)


VIEW_SQL = """\
CREATE OR REPLACE VIEW `{project}.predictions.prediction_logs` AS
SELECT
  timestamp AS logged_at,
  jsonPayload.model_version AS model_version,
  jsonPayload.merchant_hash AS merchant_hash,
  jsonPayload.features_summary.log_amount AS log_amount,
  jsonPayload.features_summary.payment_method AS payment_method,
  jsonPayload.features_summary.hour_bucket AS hour_bucket,
  jsonPayload.output.predicted_category AS predicted_category,
  jsonPayload.output.confidence AS confidence,
  jsonPayload.shadow AS shadow
FROM `{project}.predictions.run_googleapis_com_stdout`
WHERE jsonPayload.event = 'prediction'
"""

WINDOW_SQL = """\
SELECT logged_at, log_amount, payment_method, hour_bucket, predicted_category, confidence,
       merchant_hash
FROM `{project}.predictions.prediction_logs`
WHERE logged_at >= @since AND logged_at < @until AND NOT IFNULL(shadow, FALSE)
"""


class BigQueryLogSource:
    """BigQuery REST ``jobs.query``. Needs ``roles/bigquery.jobUser`` and data access (Terraform
    grants both to the pipelines account). Not run against real BigQuery in this repository."""

    def __init__(
        self,
        project: str,
        token_provider: Callable[[], str],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._project = project
        self._token = token_provider
        self._client = httpx.Client(
            base_url="https://bigquery.googleapis.com", timeout=120, transport=transport
        )

    def _query(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(
            f"/bigquery/v2/projects/{self._project}/queries",
            json={"useLegacySql": False, **body},
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        if not data.get("jobComplete", True):
            raise RuntimeError("BigQuery query did not complete within the request timeout")
        return data

    def ensure_view(self) -> None:
        """The sink writes ``run_googleapis_com_stdout``; PRD 18.4 names the view."""
        self._query({"query": VIEW_SQL.format(project=self._project)})

    def fetch(self, since: dt.datetime, until: dt.datetime) -> pd.DataFrame:
        def param(name: str, value: dt.datetime) -> dict[str, Any]:
            return {
                "name": name,
                "parameterType": {"type": "TIMESTAMP"},
                "parameterValue": {"value": value.astimezone(dt.UTC).isoformat()},
            }

        data = self._query(
            {
                "query": WINDOW_SQL.format(project=self._project),
                "parameterMode": "NAMED",
                "queryParameters": [param("since", since), param("until", until)],
            }
        )
        names = [f["name"] for f in data.get("schema", {}).get("fields", [])]
        rows = [
            {
                name: (cell or {}).get("v") if isinstance(cell, dict) else cell
                for name, cell in zip(names, row["f"], strict=True)
            }
            for row in data.get("rows", [])
        ]
        frame = pd.DataFrame(rows, columns=list(COLUMNS))
        frame["logged_at"] = pd.to_datetime(frame["logged_at"].astype(float), unit="s", utc=True)
        for column in ("log_amount", "confidence"):
            frame[column] = frame[column].astype(float)
        return frame
