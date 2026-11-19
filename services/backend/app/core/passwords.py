"""Password policy (PRD FR-01.02): 10-128 chars, not in the bundled common-password list."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 10
MAX_LENGTH = 128


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    path = Path(__file__).with_name("common_passwords.txt")
    return frozenset(
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def password_problem(password: str) -> str | None:
    """Return the field error code for a rejected password, or ``None`` if acceptable."""
    if len(password) < MIN_LENGTH:
        return "PASSWORD_TOO_SHORT"
    if len(password) > MAX_LENGTH:
        return "PASSWORD_TOO_LONG"
    if password.lower() in common_passwords():
        return "PASSWORD_TOO_COMMON"
    return None
