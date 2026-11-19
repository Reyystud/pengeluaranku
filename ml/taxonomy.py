"""Category taxonomy ``taxonomy-1`` (PRD section 4.6).

Single source of truth for category slugs, display names, and allowed transaction types.
The backend seeds its ``categories`` table from this module (T-12); the generator, the
classifier labels, and the type-consistency rule (FR-03.10) all read it too.
Changing the taxonomy requires a new ``TAXONOMY_VERSION`` and retraining.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

TAXONOMY_VERSION: Final = "taxonomy-1"

CategoryType = Literal["expense", "income", "transfer", "any"]
TransactionType = Literal["expense", "income", "transfer"]

UNCATEGORIZED: Final = "uncategorized"


@dataclass(frozen=True)
class Category:
    slug: str
    display_name: str
    transaction_type: CategoryType


CATEGORIES: Final[tuple[Category, ...]] = (
    Category("food_beverage", "Food & Beverage", "expense"),
    Category("groceries", "Groceries", "expense"),
    Category("transportation", "Transportation", "expense"),
    Category("utilities", "Utilities & Bills", "expense"),
    Category("housing", "Housing", "expense"),
    Category("shopping", "Shopping", "expense"),
    Category("entertainment", "Entertainment", "expense"),
    Category("health", "Health", "expense"),
    Category("education", "Education", "expense"),
    Category("personal_care", "Personal Care", "expense"),
    Category("gifts_donations", "Gifts & Donations", "expense"),
    Category("fees_charges", "Fees & Charges", "expense"),
    Category("other_expense", "Other Expense", "expense"),
    Category("allowance", "Allowance", "income"),
    Category("salary", "Salary", "income"),
    Category("freelance", "Freelance & Side Income", "income"),
    Category("refund", "Refund & Cashback", "income"),
    Category("other_income", "Other Income", "income"),
    Category("transfer", "Transfer & Top-up", "transfer"),
    Category(UNCATEGORIZED, "Uncategorized", "any"),
)

_BY_SLUG: Final = {c.slug: c for c in CATEGORIES}

# Labels the classifier predicts: every slug except the `uncategorized` placeholder (PRD 9.2).
MODEL_LABELS: Final[tuple[str, ...]] = tuple(c.slug for c in CATEGORIES if c.slug != UNCATEGORIZED)


def get_category(slug: str) -> Category:
    """Return the category for ``slug`` or raise ``KeyError``."""
    return _BY_SLUG[slug]


def is_valid_for_type(slug: str, transaction_type: TransactionType) -> bool:
    """True if ``slug`` may be used on a transaction of ``transaction_type``.

    ``uncategorized`` is valid for every type (PRD 4.6); an unknown slug is never valid.
    """
    category = _BY_SLUG.get(slug)
    if category is None:
        return False
    return category.transaction_type in ("any", transaction_type)
