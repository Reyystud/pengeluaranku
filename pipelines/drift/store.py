"""Where drift reports go (PRD 18.3): ``<root>/drift/YYYY-MM-DD/{report.html,summary.json}``.

``LocalStore`` writes under a directory (default ``data/reports``); ``GcsStore`` uploads to
``gs://<project>-reports`` through the JSON API with an OAuth token. Both keep the daily
summaries so the unseen-merchant median needs no extra database.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class ReportStore(Protocol):
    def save(self, day: dt.date, html: str | None, summary: dict[str, Any]) -> str: ...
    def history(self, before: dt.date, days: int) -> list[float]: ...


def _path(day: dt.date, name: str) -> str:
    return f"drift/{day.isoformat()}/{name}"


class LocalStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, day: dt.date, html: str | None, summary: dict[str, Any]) -> str:
        out = self._root / _path(day, "summary.json").rsplit("/", 1)[0]
        out.mkdir(parents=True, exist_ok=True)
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if html is not None:
            (out / "report.html").write_text(html, encoding="utf-8")
        return str(out)

    def history(self, before: dt.date, days: int) -> list[float]:
        """Unseen-merchant shares of the ``days`` days before ``before``, oldest first."""
        values = []
        for offset in range(days, 0, -1):
            path = self._root / _path(before - dt.timedelta(days=offset), "summary.json")
            if path.exists():
                share = json.loads(path.read_text(encoding="utf-8")).get("unseen_merchant_share")
                if share is not None:
                    values.append(float(share))
        return values


class GcsStore:
    def __init__(
        self,
        bucket: str,
        token_provider: Callable[[], str],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._bucket = bucket
        self._token = token_provider
        self._client = httpx.Client(
            base_url="https://storage.googleapis.com", timeout=60, transport=transport
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _upload(self, name: str, body: bytes, content_type: str) -> None:
        response = self._client.post(
            f"/upload/storage/v1/b/{self._bucket}/o",
            params={"uploadType": "media", "name": name},
            content=body,
            headers={**self._headers(), "Content-Type": content_type},
        )
        response.raise_for_status()

    def save(self, day: dt.date, html: str | None, summary: dict[str, Any]) -> str:
        self._upload(_path(day, "summary.json"), json.dumps(summary).encode(), "application/json")
        if html is not None:
            self._upload(_path(day, "report.html"), html.encode(), "text/html")
        return f"gs://{self._bucket}/drift/{day.isoformat()}/"

    def history(self, before: dt.date, days: int) -> list[float]:
        values = []
        for offset in range(days, 0, -1):
            name = quote(_path(before - dt.timedelta(days=offset), "summary.json"), safe="")
            response = self._client.get(
                f"/storage/v1/b/{self._bucket}/o/{name}",
                params={"alt": "media"},
                headers=self._headers(),
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            share = response.json().get("unseen_merchant_share")
            if share is not None:
                values.append(float(share))
        return values
