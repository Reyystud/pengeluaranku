"""Integrity checks for the T-02 config files (taxonomy-linked merchants, aliases, holidays)."""

import re
import unicodedata
from collections import Counter

from ml.config import load_aliases, load_cities, load_holidays, load_merchants
from ml.taxonomy import CATEGORIES, MODEL_LABELS


def simple_key(text: str) -> str:
    """Rough normalization for tests only; the real one is ml/preprocessing (T-07)."""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


# ---- merchants -------------------------------------------------------------------------


def test_every_model_label_has_merchants() -> None:
    covered = {m.category for m in load_merchants()}
    assert covered == set(MODEL_LABELS)


def test_merchant_counts_per_category() -> None:
    counts = Counter(m.category for m in load_merchants())
    types = {c.slug: c.transaction_type for c in CATEGORIES}
    for slug, n in counts.items():
        minimum = 5 if types[slug] == "income" else 15
        assert n >= minimum, f"{slug} has only {n} merchants (need >= {minimum})"


def test_merchant_names_unique_across_categories() -> None:
    keys = [simple_key(m.name) for m in load_merchants()]
    duplicates = [k for k, n in Counter(keys).items() if n > 1]
    assert not duplicates


def test_merchant_weights_positive_and_ambiguity_slugs_valid() -> None:
    valid = set(MODEL_LABELS)
    for m in load_merchants():
        assert m.weight > 0
        assert set(m.ambiguous_with) <= valid
        assert m.category not in m.ambiguous_with


# ---- aliases ---------------------------------------------------------------------------


def test_alias_keys_are_normalized_form() -> None:
    for key in load_aliases():
        assert key == simple_key(key), key


def test_alias_targets_are_known_merchants() -> None:
    known = {simple_key(m.name) for m in load_merchants()}
    for alias, target in load_aliases().items():
        assert target in known, f"{alias!r} -> {target!r} is not a merchant"


def test_aliases_have_no_chains_or_self_maps() -> None:
    aliases = load_aliases()
    for alias, target in aliases.items():
        assert alias != target
        assert target not in aliases, f"chain: {alias} -> {target} -> {aliases[target]}"


def test_alias_keys_do_not_shadow_a_real_merchant() -> None:
    known = {simple_key(m.name) for m in load_merchants()}
    assert not set(load_aliases()) & known


# ---- cities ----------------------------------------------------------------------------


def test_cities_lowercase_alnum() -> None:
    cities, abbreviations = load_cities()
    for token in cities | abbreviations:
        assert token == simple_key(token)
    assert "jakarta" in cities and "jkt" in abbreviations


# ---- holidays --------------------------------------------------------------------------


def test_holidays_cover_2025_to_2027() -> None:
    years, holidays = load_holidays()
    assert years == (2025, 2026, 2027)
    assert {h.day.year for h in holidays} == {2025, 2026, 2027}


def test_holiday_counts_match_official_skb() -> None:
    _, holidays = load_holidays()
    counts = Counter((h.day.year, h.kind) for h in holidays)
    # 2025: 17 national + 10 collective in the original SKB, +1 (18 Aug) by the 2025-08-07 amendment
    assert counts[(2025, "national")] == 17
    assert counts[(2025, "collective_leave")] == 11
    assert counts[(2026, "national")] == 17
    assert counts[(2026, "collective_leave")] == 8
    assert counts[(2027, "national")] == 18
    assert counts[(2027, "collective_leave")] == 8


def test_holiday_dates_unique() -> None:
    _, holidays = load_holidays()
    days = [h.day for h in holidays]
    assert len(days) == len(set(days))


def test_fixed_date_holidays_present_every_year() -> None:
    _, holidays = load_holidays()
    national = {h.day.isoformat() for h in holidays if h.kind == "national"}
    for year in (2025, 2026, 2027):
        for md in ("01-01", "05-01", "06-01", "08-17", "12-25"):
            assert f"{year}-{md}" in national
