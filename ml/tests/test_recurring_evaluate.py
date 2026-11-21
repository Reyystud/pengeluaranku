"""Recurring detector evaluation against generator labels (PRD 7.8): counting rules."""

from __future__ import annotations

from typing import Any

from ml.recurring.evaluate import evaluate_user


def row(
    date: str, desc: str, amount: int, series: str | None, kind: str = "expense"
) -> dict[str, Any]:
    return {
        "date": date,
        "description": desc,
        "merchant": None,
        "amount": amount,
        "type": kind,
        "recurring_series_id": series,
    }


def monthly_rows(
    desc: str, series: str | None, months: int = 5, kind: str = "expense"
) -> list[Any]:
    return [
        row(f"2026-{m:02d}-05 10:00", desc, 55000, series, kind) for m in range(11 - months + 1, 12)
    ]


def test_a_labelled_series_is_found_and_counted_once() -> None:
    result = evaluate_user(monthly_rows("NETFLIX.COM", "u1-sub0"))
    assert (result["true_positive"], result["false_positive"]) == (1, 0)
    assert (result["ground_truth"], result["recalled"]) == (1, 1)


def test_an_unlabelled_regular_expense_counts_as_false_positive() -> None:
    result = evaluate_user(monthly_rows("GYM MEMBER", None))
    assert (result["true_positive"], result["false_positive"], result["ground_truth"]) == (0, 1, 0)


def test_income_series_are_reported_separately_not_scored() -> None:
    result = evaluate_user(monthly_rows("GAJI PT MAJU", None, kind="income"))
    assert result["income_detected"] == 1 and result["detected_expense"] == 0


def test_a_labelled_series_with_fewer_than_three_months_is_not_a_miss() -> None:
    result = evaluate_user(monthly_rows("SPOTIFY", "u1-sub1", months=2))
    assert result["ground_truth"] == 0
