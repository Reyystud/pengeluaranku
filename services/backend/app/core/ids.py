"""Identifier helpers: ULIDs for request IDs (PRD 13.1.3)."""

from __future__ import annotations

import os
import re
import time
import uuid

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


def new_uuid7(now_ms: int | None = None) -> uuid.UUID:
    """UUIDv7 (RFC 9562): 48-bit ms timestamp, version 7, variant 10, 74 random bits.

    Time-ordered, so B-tree indexes on primary keys stay append-friendly (PRD 4.1).
    """
    millis = int(time.time() * 1000) if now_ms is None else now_ms
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand >> 68) & 0xFFF  # 12 bits
    rand_b = rand & ((1 << 62) - 1)  # 62 bits
    value = (millis & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)
