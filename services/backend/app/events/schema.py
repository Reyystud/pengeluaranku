"""JSON Schemas of the events (PRD 14.3, ``schemas/events/<type>.v<n>.json``).

Producer and consumer both validate against them: the outbox refuses to write a payload that
breaks its schema, and the push endpoint refuses a message that does not match.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[4] / "schemas" / "events"


class InvalidEvent(ValueError):
    """The envelope does not match the schema of its type. The message never echoes values."""


@cache
def _validator(event_type: str, version: int) -> Draft202012Validator | None:
    path = SCHEMA_DIR / f"{event_type}.v{version}.json"
    if not path.is_file():
        return None
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def validate_envelope(envelope: Any) -> None:
    """Raise ``InvalidEvent`` unless ``envelope`` is a known event of a supported version."""
    if not isinstance(envelope, dict):
        raise InvalidEvent("envelope is not an object")
    event_type, version = envelope.get("event_type"), envelope.get("schema_version")
    if not isinstance(event_type, str) or not isinstance(version, int):
        raise InvalidEvent("event_type or schema_version is missing")
    validator = _validator(event_type, version)
    if validator is None:
        raise InvalidEvent(f"unknown event {event_type!r} version {version}")
    error = next(iter(validator.iter_errors(envelope)), None)
    if error is not None:
        where = ".".join(str(p) for p in error.absolute_path) or "<root>"
        raise InvalidEvent(f"{event_type} does not match its schema at {where}")
