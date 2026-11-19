"""Merchant normalization and description preprocessing (PRD 7.3.2, 7.3.3).

``normalize_merchant`` is pure and deterministic: the same string always gives the same key, in the
backend, the ML service and the training pipeline. Aliases and city names come from versioned files
in ``config/`` (``merchant_aliases.yaml``, ``cities_id.yaml``).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from ml.config import load_aliases, load_cities

MAX_KEY_LENGTH = 64
DERIVED_KEY_TOKENS = 3
DERIVED_MERCHANT_TOKENS = 2

# Step 2: payment prefixes/suffixes. Only stripped at the start or end of the text, as whole
# tokens, so a merchant that merely contains one of these words in the middle is untouched.
_PAYMENT_WORDS: tuple[tuple[str, ...], ...] = (
    ("transfer", "ke"),
    ("qris",),
    ("qr",),
    ("pos",),
    ("edc",),
    ("trf",),
    ("pembayaran",),
    ("payment",),
    ("byr",),
    ("debit",),
    ("purchase",),
    ("pmb",),
)

# Step 3: platform wrappers. Removed only when another token follows.
_WRAPPER_NAMES = r"(?:gopay|ovo|dana|shopeepay|linkaja)"
_WRAPPER_SEPARATED = re.compile(rf"^{_WRAPPER_NAMES}\s*[*/\-]\s*(?=\S)")
_WRAPPER_SPACE = re.compile(rf"^{_WRAPPER_NAMES}\s+(?=\S)")

# Step 4: reference numbers.
_DIGIT_RUN = re.compile(r"\d{4,}")
_DATE_TOKEN = re.compile(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}$")
_INVOICE_TOKEN = re.compile(r"^(?:inv|invoice|ref|trx)[/\-.:#]")

# Step 5: location suffix separators and branch words.
_LOCATION_SPLIT = re.compile(r"\s+-\s+|\s+@\s*|\s*@\s+")
_BRANCH_WORDS = frozenset({"cab", "cabang", "outlet", "store", "branch"})

_NON_WORD = re.compile(r"[\W_]+")
_SPACES = re.compile(r"\s+")


def _is_reference(token: str) -> bool:
    return bool(
        token.startswith("#")
        or _DIGIT_RUN.search(token)
        or _DATE_TOKEN.match(token)
        or _INVOICE_TOKEN.match(token)
    )


def strip_reference_numbers(text: str) -> str:
    """Remove reference-number tokens (step 4); input is expected to be lowercase."""
    return " ".join(t for t in text.split() if not _is_reference(t))


def _strip_payment_words(tokens: list[str]) -> list[str]:
    changed = True
    while changed and tokens:
        changed = False
        for words in _PAYMENT_WORDS:
            n = len(words)
            if len(tokens) > n and tuple(tokens[:n]) == words:
                tokens = tokens[n:]
                changed = True
            elif len(tokens) > n and tuple(tokens[-n:]) == words:
                tokens = tokens[:-n]
                changed = True
    return tokens


def _strip_trailing_cities(
    tokens: list[str], cities: frozenset[str], abbrevs: frozenset[str]
) -> list[str]:
    changed = True
    while changed and tokens:
        changed = False
        for size in (3, 2, 1):
            if len(tokens) > size and " ".join(tokens[-size:]) in cities:
                tokens = tokens[:-size]
                changed = True
                break
        else:
            if len(tokens) > 1 and tokens[-1] in abbrevs:
                tokens = tokens[:-1]
                changed = True
    return tokens


def _strip_branch_words(tokens: list[str]) -> list[str]:
    out: list[str] = []
    skip_number = False
    for token in tokens:
        if token in _BRANCH_WORDS:
            skip_number = True
            continue
        if skip_number and token.isdigit():
            skip_number = False
            continue
        skip_number = False
        out.append(token)
    return out


@lru_cache(maxsize=200_000)
def normalize_merchant(raw: str) -> str:
    """Normalize a merchant name or description to a grouping key (PRD 7.3.2). Never raises."""
    cities, abbrevs = load_cities()
    aliases = load_aliases()

    # 1. NFKC + lowercase
    text = unicodedata.normalize("NFKC", raw).lower().strip()

    # 2. payment prefixes / suffixes
    text = " ".join(_strip_payment_words(text.split()))

    # 3. platform wrappers (keep the merchant)
    text = _WRAPPER_SEPARATED.sub("", text, count=1) or text
    text = _WRAPPER_SPACE.sub("", text, count=1)

    # 4. reference numbers
    text = strip_reference_numbers(text)

    # 5. location suffix after " - " / " @ ", branch tokens, trailing city names
    text = _LOCATION_SPLIT.split(text, maxsplit=1)[0]
    tokens = _strip_branch_words(text.split())

    # 6. non-alphanumeric -> space (done before city matching so "jakarta," still matches)
    tokens = _SPACES.sub(" ", _NON_WORD.sub(" ", " ".join(tokens))).strip().split()
    with_city = " ".join(tokens)
    # An alias may itself end in a city word (``trans jakarta`` -> ``transjakarta``).
    if with_city in aliases:
        return aliases[with_city][:MAX_KEY_LENGTH].rstrip()
    tokens = _strip_trailing_cities(tokens, cities, abbrevs)
    text = " ".join(tokens)

    # 7. alias map (whole string)
    text = aliases.get(text, text)

    # 8. truncate
    return text[:MAX_KEY_LENGTH].rstrip()


def preprocess_description(text: str) -> str:
    """Classifier input text (PRD 7.3.3): NFKC, lowercase, no reference numbers, one space.

    Typos are deliberately not corrected; character n-grams absorb them.
    """
    lowered = unicodedata.normalize("NFKC", text).lower()
    return _SPACES.sub(" ", strip_reference_numbers(lowered)).strip()


def derive_merchant_key(description: str) -> str:
    """``merchant_key`` when no merchant was given: first 3 tokens of the normalized text."""
    return " ".join(normalize_merchant(description).split()[:DERIVED_KEY_TOKENS])


def derive_merchant(description: str) -> str:
    """Display merchant when none was given: title-cased first 2 tokens of the normalized text."""
    return " ".join(normalize_merchant(description).split()[:DERIVED_MERCHANT_TOKENS]).title()


def resolve_merchant(merchant: str | None, description: str) -> tuple[str, str]:
    """Return ``(merchant, merchant_key)`` following PRD 7.3.2 for given or missing merchants."""
    if merchant is not None and merchant.strip():
        return merchant.strip()[:100], normalize_merchant(merchant)
    return derive_merchant(description), derive_merchant_key(description)
