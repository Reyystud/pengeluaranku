import pytest

from ml.taxonomy import (
    CATEGORIES,
    MODEL_LABELS,
    TAXONOMY_VERSION,
    UNCATEGORIZED,
    get_category,
    is_valid_for_type,
)


def test_taxonomy_version() -> None:
    assert TAXONOMY_VERSION == "taxonomy-1"


def test_category_counts_match_prd_4_6() -> None:
    by_type: dict[str, int] = {}
    for c in CATEGORIES:
        by_type[c.transaction_type] = by_type.get(c.transaction_type, 0) + 1
    assert by_type == {"expense": 13, "income": 5, "transfer": 1, "any": 1}
    assert len(CATEGORIES) == 20


def test_slugs_unique_and_snake_case() -> None:
    slugs = [c.slug for c in CATEGORIES]
    assert len(slugs) == len(set(slugs))
    assert all(s.replace("_", "").isalpha() and s == s.lower() for s in slugs)


def test_model_labels_exclude_uncategorized() -> None:
    assert UNCATEGORIZED not in MODEL_LABELS
    assert len(MODEL_LABELS) == 19


def test_uncategorized_is_valid_for_every_type() -> None:
    for tx_type in ("expense", "income", "transfer"):
        assert is_valid_for_type(UNCATEGORIZED, tx_type)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("slug", "tx_type", "expected"),
    [
        ("food_beverage", "expense", True),
        ("food_beverage", "income", False),
        ("salary", "income", True),
        ("salary", "expense", False),
        ("transfer", "transfer", True),
        ("transfer", "expense", False),
        ("does_not_exist", "expense", False),
    ],
)
def test_fr_03_10_type_validity(slug: str, tx_type: str, expected: bool) -> None:
    assert is_valid_for_type(slug, tx_type) is expected  # type: ignore[arg-type]


def test_get_category_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_category("nope")
