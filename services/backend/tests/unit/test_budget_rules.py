"""Pure budget rules (PRD 7.5): status boundaries, utilization, input schemas."""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.schemas.budgets import BudgetCreate, BudgetUpdate
from app.services.budgets import one_decimal, status_of, utilization_percent
from pydantic import ValidationError

D = Decimal


@pytest.mark.parametrize(
    ("percent", "status"),
    [
        ("0", "healthy"),
        ("49.9999", "healthy"),
        ("50", "normal"),
        ("79.9999", "normal"),
        ("80", "warning"),
        ("99.9999", "warning"),
        ("100", "exceeded"),
        ("100.0001", "exceeded"),
        ("5000", "exceeded"),
    ],
)
def test_fr_05_04_status_boundaries(percent: str, status: str) -> None:
    assert status_of(D(percent)) == status


def test_fr_05_03_utilization_is_exact_and_rounded_only_for_display() -> None:
    assert utilization_percent(D("1"), D("3")) > D("33.3333")
    assert one_decimal(utilization_percent(D("1"), D("3"))) == D("33.3")
    assert one_decimal(D("12.25")) == D("12.3")  # half up
    assert utilization_percent(D("0"), D("10")) == 0


def test_fr_05_05_threshold_normalisation_and_limits() -> None:
    assert BudgetCreate(limit_amount=D("1"), alert_thresholds=[100, 80, 80]).alert_thresholds == [
        80,
        100,
    ]
    assert BudgetCreate(limit_amount=D("1")).alert_thresholds is None  # service applies [80, 100]
    for bad in ([0], [201], [-1], list(range(1, 12))):
        with pytest.raises(ValidationError):
            BudgetCreate(limit_amount=D("1"), alert_thresholds=bad)
    assert BudgetUpdate(alert_thresholds=[1, 200]).alert_thresholds == [1, 200]


def test_fr_05_03_limit_must_be_positive_finite_and_two_decimals() -> None:
    assert BudgetCreate(limit_amount=D("0.01")).limit_amount == D("0.01")
    for bad in ("0", "-1", "0.001", "NaN", "Infinity", "10000000000000"):
        with pytest.raises(ValidationError):
            BudgetCreate(limit_amount=D(bad))
