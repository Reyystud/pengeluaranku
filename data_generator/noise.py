"""Text noise for transaction descriptions (PRD 10.1 "Text noise")."""

from __future__ import annotations

from typing import Any

import numpy as np

PREFIXES: dict[str, tuple[str, ...]] = {
    "qris": ("QRIS", "QR"),
    "e_wallet": ("GOPAY*", "OVO/", "DANA ", "SHOPEEPAY - "),
    "debit_card": ("POS", "EDC", "DEBIT"),
    "credit_card": ("POS", "PURCHASE"),
    "bank_transfer": ("TRF", "TRANSFER KE", "PEMBAYARAN"),
    "cash": (),
    "other": ("PAYMENT", "BYR"),
}
LOCATIONS: tuple[str, ...] = (
    "JKT SELATAN",
    "JKT BARAT",
    "BDG",
    "SBY",
    "BSD",
    "DEPOK",
    "BEKASI",
    "TANGERANG",
    "YOGYAKARTA",
    "MALANG",
)
BRANCH_WORDS: tuple[str, ...] = ("CAB", "OUTLET", "STORE", "BRANCH")
NOTES: tuple[str, ...] = (
    "bareng teman",
    "bulanan",
    "darurat",
    "kantor",
    "weekend",
    "traktir",
    "titipan",
)


def pick(rng: np.random.Generator, items: tuple[str, ...] | list[str]) -> str:
    return items[int(rng.integers(len(items)))]


def apply_typo(rng: np.random.Generator, text: str) -> str:
    """One-character edit (delete, swap with neighbour, or replace) on an alphabetic position."""
    positions = [i for i, ch in enumerate(text) if ch.isalpha()]
    if len(positions) < 4:
        return text
    i = positions[int(rng.integers(len(positions)))]
    op = int(rng.integers(3))
    if op == 0:
        return text[:i] + text[i + 1 :]
    if op == 1 and i + 1 < len(text) and text[i + 1].isalpha():
        return text[:i] + text[i + 1] + text[i] + text[i + 2 :]
    letter = "abcdefghijklmnopqrstuvwxyz"[int(rng.integers(26))]
    return text[:i] + letter + text[i + 1 :]


def apply_case(rng: np.random.Generator, text: str, probs: dict[str, float]) -> str:
    keys = ("as_is", "upper", "lower", "random")
    weights = np.array([probs[k] for k in keys], dtype=float)
    choice = keys[int(rng.choice(len(keys), p=weights / weights.sum()))]
    if choice == "upper":
        return text.upper()
    if choice == "lower":
        return text.lower()
    if choice == "random":
        flips = rng.random(len(text)) < 0.5
        return "".join(
            ch.upper() if flip else ch.lower() for ch, flip in zip(text, flips, strict=True)
        )
    return text


def reference_token(rng: np.random.Generator) -> str:
    kind = int(rng.integers(3))
    if kind == 0:
        return str(int(rng.integers(10**3, 10**10)))
    if kind == 1:
        return f"#{int(rng.integers(10**4, 10**6))}"
    return f"INV/2025/{int(rng.integers(10**5, 10**7))}"


def make_description(
    rng: np.random.Generator,
    base: str,
    abbrevs: tuple[str, ...],
    payment_method: str,
    noise: dict[str, Any],
) -> str:
    """Build a noisy description from a clean merchant/counterparty name."""
    scale = float(noise["scale"])

    def chance(p: float) -> bool:
        return bool(rng.random() < min(1.0, p * scale))

    text = base
    if abbrevs and chance(float(noise["abbrev_prob"])):
        text = pick(rng, abbrevs)
    if chance(float(noise["typo_prob"])):
        text = apply_typo(rng, text)

    parts = [text]
    prefixes = PREFIXES.get(payment_method, ())
    if prefixes and chance(float(noise["prefix_prob"])):
        prefix = pick(rng, prefixes)
        parts = [prefix + ("" if prefix.endswith(("*", "/", " ", "-")) else " ") + text]
    if chance(float(noise["reference_prob"])):
        parts.append(reference_token(rng))
    if chance(float(noise["location_prob"])):
        if rng.random() < 0.5:
            parts.append(f"- {pick(rng, LOCATIONS)}")
        else:
            parts.append(f"@ {pick(rng, LOCATIONS)}")
    elif chance(0.05):
        parts.append(f"{pick(rng, BRANCH_WORDS)} {int(rng.integers(1, 40))}")

    result = " ".join(parts)
    result = apply_case(rng, result, noise["case_probs"])
    return result[:200].strip() or base
