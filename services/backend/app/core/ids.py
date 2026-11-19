"""Identifier helpers: ULIDs for request IDs (PRD 13.1.3)."""

from __future__ import annotations

import os
import re
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def new_ulid(now_ms: int | None = None) -> str:
    """26-character ULID: 48-bit ms timestamp + 80 random bits, lexicographically sortable."""
    millis = int(time.time() * 1000) if now_ms is None else now_ms
    value = (millis << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))
