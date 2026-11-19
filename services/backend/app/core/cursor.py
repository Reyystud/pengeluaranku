"""Signed opaque pagination cursors (PRD 13.1.4): base64url(payload) + HMAC-SHA256 signature."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass

from app.core.errors import ProblemError


@dataclass(frozen=True)
class Cursor:
    sort: str  # "date" | "amount"
    key: str  # sort value as text (ISO datetime or decimal string)
    id: uuid.UUID


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def invalid_cursor() -> ProblemError:
    return ProblemError(400, "INVALID_CURSOR", "Invalid cursor", "The cursor is not valid.")


def encode_cursor(cursor: Cursor, user_id: uuid.UUID, secret: str) -> str:
    body = json.dumps(
        {"s": cursor.sort, "k": cursor.key, "i": str(cursor.id), "u": str(user_id)},
        separators=(",", ":"),
    )
    payload = _b64(body.encode())
    return f"{payload}.{_sign(payload, secret)}"


def decode_cursor(token: str, user_id: uuid.UUID, secret: str, expected_sort: str) -> Cursor:
    """Verify signature, owner and sort mode; any failure is ``INVALID_CURSOR`` (400)."""
    try:
        payload, _, signature = token.partition(".")
        if not payload or not hmac.compare_digest(signature, _sign(payload, secret)):
            raise invalid_cursor()
        data = json.loads(_unb64(payload))
        if data["u"] != str(user_id) or data["s"] != expected_sort:
            raise invalid_cursor()
        return Cursor(sort=data["s"], key=str(data["k"]), id=uuid.UUID(data["i"]))
    except ProblemError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise invalid_cursor() from exc
