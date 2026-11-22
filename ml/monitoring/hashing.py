"""Merchant hash used in prediction logs and in the reference vocabulary (PRD 18.3, 18.4).

Prediction logs never carry a merchant name (PRD 17.3). The drift job still has to tell whether a
merchant was seen in training, so both sides compare this 12-character hash of the normalized
merchant key. Training and serving import this one function: they cannot disagree.
"""

from __future__ import annotations

import hashlib


def merchant_hash(merchant_key: str) -> str | None:
    """First 12 hex characters of SHA-256 of the key; ``None`` when there is no merchant."""
    key = merchant_key.strip().lower()
    return hashlib.sha256(key.encode()).hexdigest()[:12] if key else None
