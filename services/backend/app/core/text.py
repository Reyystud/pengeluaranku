"""Input hygiene for user text: control characters and card-number masking (PRD 7.2.1, 17.2)."""

from __future__ import annotations

import re
import unicodedata

# 13-19 digits, optionally separated by single spaces or dashes (a card or account number).
_LONG_NUMBER = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def clean_text(value: str, *, keep_newlines: bool = False) -> str:
    """Trim and replace control characters with a space (newlines kept when asked)."""
    out = []
    for ch in value:
        if ch == "\n" and keep_newlines:
            out.append(ch)
        elif unicodedata.category(ch) == "Cc":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out).strip()


def mask_long_numbers(value: str) -> str:
    """Replace a 13-19 digit number by ``****`` plus its last 4 digits, before storage (17.2)."""

    def _mask(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return f"****{digits[-4:]}" if 13 <= len(digits) <= 19 else match.group(0)

    return _LONG_NUMBER.sub(_mask, value)
