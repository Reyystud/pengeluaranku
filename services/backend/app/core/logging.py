"""Structured JSON logging with sensitive-data redaction (PRD 17.3).

Rules enforced here: never log descriptions, merchant names, notes, amounts, emails, passwords,
tokens, cookies, Authorization headers, raw CSV or raw user ids. Log ``user_pseudo_id`` and, when a
fingerprint is useful, ``description_length`` / ``description_hash``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, TextIO

import structlog

REDACTED = "[REDACTED]"
FORBIDDEN_KEYS = frozenset(
    {
        "description",
        "merchant",
        "merchant_name",
        "notes",
        "note",
        "amount",
        "email",
        "password",
        "new_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set-cookie",
        "csv",
        "raw_csv",
        "body",
        "user_id",
        "secret",
        "jwt_secret",
    }
)
_VALUE_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
)


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in _VALUE_PATTERNS:
            value = pattern.sub(REDACTED, value)
        return value
    if isinstance(value, Mapping):
        return {
            k: REDACTED if str(k).lower() in FORBIDDEN_KEYS else _clean(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    return value


def redact_sensitive(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: blank forbidden keys and scrub token/email-looking string values."""
    for key in list(event_dict):
        if key.lower() in FORBIDDEN_KEYS:
            event_dict[key] = REDACTED
        elif key not in {"exception", "stack"}:
            event_dict[key] = _clean(event_dict[key])
    return event_dict


def pseudonymize(user_id: str, key: str) -> str:
    """Stable pseudonymous id: first 16 hex chars of HMAC-SHA256(key, user_id)."""
    return hmac.new(key.encode(), user_id.encode(), hashlib.sha256).hexdigest()[:16]


def description_fingerprint(description: str) -> dict[str, Any]:
    """Debug-safe summary of a description (PRD 17.3): length and a short hash, never the text."""
    return {
        "description_length": len(description),
        "description_hash": hashlib.sha256(description.encode()).hexdigest()[:12],
    }


def _severity(
    _logger: Any, method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["severity"] = {"warn": "WARNING", "exception": "ERROR"}.get(method, method.upper())
    return event_dict


def configure_logging(level: str, service: str, stream: TextIO | None = None) -> None:
    """Configure structlog and route stdlib logging through the same JSON pipeline."""
    out = stream or sys.stdout

    def add_service(
        _l: Any, _m: str, event_dict: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        event_dict["service"] = service
        return event_dict

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _severity,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        add_service,
        redact_sensitive,
        structlog.processors.format_exc_info,
    ]
    structlog.configure(
        processors=[*shared, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=out),
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(out)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared[1:],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # our middleware logs one line per request
    for chatty in ("httpx", "httpcore"):
        logging.getLogger(chatty).setLevel(logging.WARNING)  # client URLs can carry query text
