"""Event publishers (PRD 7.11, 14.3). The relay depends on this interface, not on Google Cloud.

``PubSubPublisher`` talks to the Pub/Sub REST API with ``httpx``: against Google it authenticates
with application default credentials (the worker's service account), against the emulator
(``PUBSUB_EMULATOR_HOST``) it needs no credentials.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import httpx

from app.core.config import Settings

PUBSUB_URL = "https://pubsub.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/pubsub"


class EventPublisher(Protocol):
    def publish(self, envelopes: Sequence[dict[str, Any]]) -> None:
        """Publish all envelopes or raise. Order is not guaranteed (PRD FR-11.04)."""


class InMemoryPublisher:
    """Collects envelopes; tests use it as the bus."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish(self, envelopes: Sequence[dict[str, Any]]) -> None:
        self.published.extend(envelopes)


def _google_token() -> str:
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=[SCOPE])
    credentials.refresh(Request())
    return str(credentials.token)


class PubSubPublisher:
    def __init__(
        self,
        project_id: str,
        topic: str,
        *,
        emulator_host: str = "",
        token_provider: Callable[[], str] = _google_token,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = (
            f"{'http://' + emulator_host if emulator_host else PUBSUB_URL}"
            f"/v1/projects/{project_id}/topics/{topic}:publish"
        )
        self._authenticated = not emulator_host
        self._token_provider = token_provider
        self._client = httpx.Client(timeout=10, transport=transport)

    def publish(self, envelopes: Sequence[dict[str, Any]]) -> None:
        if not envelopes:
            return
        messages = [
            {
                "data": base64.b64encode(json.dumps(e, separators=(",", ":")).encode()).decode(),
                # Duplicated as attributes for filtering (PRD 14.3).
                "attributes": {
                    "event_type": str(e["event_type"]),
                    "schema_version": str(e["schema_version"]),
                },
            }
            for e in envelopes
        ]
        headers = (
            {"Authorization": f"Bearer {self._token_provider()}"} if self._authenticated else {}
        )
        response = self._client.post(self._url, json={"messages": messages}, headers=headers)
        response.raise_for_status()
        if len(response.json().get("messageIds", [])) != len(messages):
            raise RuntimeError("pubsub acknowledged fewer messages than were sent")


def build_publisher(settings: Settings) -> EventPublisher:
    return PubSubPublisher(
        settings.pubsub_project_id,
        settings.pubsub_topic,
        emulator_host=settings.pubsub_emulator_host,
    )
