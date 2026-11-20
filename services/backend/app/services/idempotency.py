"""``Idempotency-Key`` handling (PRD 13.1.5).

The key row is claimed inside the request's own DB transaction. A concurrent request with the same
key waits on the unique index until the first one ends, then replays the stored response (so the
in-flight case never double-writes). A failed request rolls back, key included, so retry works.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import ProblemError
from app.repositories import IdempotencyRepository

TTL = dt.timedelta(hours=24)
KEY_MIN, KEY_MAX = 8, 128


@dataclass
class Replay:
    status: int
    body: dict[str, Any]


def request_hash(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{method}\n{path}\n{canonical}".encode()).hexdigest()


def validate_key(key: str | None, *, required: bool) -> str | None:
    if key is None or key == "":
        if required:
            raise ProblemError(
                400,
                "IDEMPOTENCY_KEY_REQUIRED",
                "Idempotency-Key required",
                "Send an Idempotency-Key header (8-128 characters) with this request.",
            )
        return None
    if not (KEY_MIN <= len(key) <= KEY_MAX):
        raise ProblemError(
            400,
            "BAD_REQUEST",
            "Bad request",
            "Idempotency-Key must be between 8 and 128 characters.",
        )
    return key


class IdempotencyService:
    def __init__(self, session: Session) -> None:
        self.repo = IdempotencyRepository(session)

    def begin(
        self, user_id: uuid.UUID, key: str, method: str, path: str, body: Any
    ) -> Replay | None:
        """``None`` if the caller should run the request, else the stored response to replay."""
        digest = request_hash(method, path, body)
        self.repo.purge_expired(user_id, key, dt.datetime.now(dt.UTC) - TTL)
        if self.repo.claim(user_id, key, method, path, digest):
            return None
        row = self.repo.get(user_id, key)
        if row is None or row.request_hash != digest:
            raise ProblemError(
                409,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency key reused",
                "This Idempotency-Key was already used with a different request.",
            )
        if row.response_status is None or row.response_body is None:
            raise ProblemError(
                409,
                "CONFLICT",
                "Conflict",
                "A request with this Idempotency-Key is still in progress.",
                headers={"Retry-After": "1"},
            )
        return Replay(row.response_status, row.response_body)

    def complete(self, user_id: uuid.UUID, key: str, status: int, body: dict[str, Any]) -> None:
        self.repo.complete(user_id, key, status, body)
