"""FR-09 rule catalogue (PRD 7.9): every threshold at, just under and just over its boundary."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from app.services.insight_config import load_insight_config
from app.services.insight_rules import (
    BudgetPace,
    CategoryDelta,
    Facts,
    PriceChange,
    WeekendFacts,
    evaluate,
    idr,
    ins_01,
    ins_02,
    ins_03,
    ins_04,
    ins_05,
    ins_06,
    ins_07,
    ins_08,
    ins_09,
    whole,
)

CFG = load_insight_config()
D = Decimal


def facts(**over: object) -> Facts:
    base: dict[str, object] = {
        "period_start": dt.date(2026, 11, 1),
        "period_end": dt.date(2026, 11, 30),
        "previous_start": dt.date(2026, 10, 1),
        "previous_end": dt.date(2026, 10, 31),
        "elapsed_days": 20,
        "previous_complete": True,
    }
    base.update(over)
    return Facts(**base)  # type: ignore[arg-type]


def test_fr_09_formatting_helpers() -> None:
    assert idr(D("1250000")) == "Rp1.250.000"
    assert idr(D("25000.4")) == "Rp25.000"
    assert idr(D("-5000")) == "-Rp5.000"
    assert whole(D("19.5")) == 20 and whole(D("-19.5")) == -20 and whole(D("19.49")) == 19


def test_fr_09_config_is_versioned_and_complete() -> None:
    assert CFG.version == "insights-1" and CFG.dashboard_top == 3
    for n in range(1, 10):
        assert CFG.rule_version(f"INS-0{n}") == "1"


@pytest.mark.parametrize(
    ("current", "previous", "fires"),
    [
        ("120000", "100000", False),  # +20% but only Rp20.000
        ("150000", "100000", True),  # +50%, exactly Rp50.000: both limits are inclusive
        ("149999", "100000", False),  # one rupiah under the delta limit
        ("40000", "100000", True),  # -60%, Rp60.000: decreases count too
        ("55000", "100000", False),  # -45%, Rp45.000
        ("150000", "99999", False),  # previous under Rp100.000
        ("110000", "100000", False),  # +10%
        ("1200000", "1000000", True),  # exactly +20% and Rp200.000
        ("1199999", "1000000", False),  # just under +20%
    ],
)
def test_fr_09_ins_01_boundaries(current: str, previous: str, fires: bool) -> None:
    cats = [CategoryDelta("food_beverage", "Food & Beverage", D(current), D(previous))]
    out = ins_01(facts(categories=cats), CFG)
    assert bool(out) is fires
    if fires:
        delta = D(current) - D(previous)
        c = out[0]
        assert c.severity == ("warning" if delta > 0 else "positive")
        assert c.message_params["direction"] == ("up" if delta > 0 else "down")
        assert c.evidence["metrics"]["delta"] == f"{delta:.2f}"


def test_fr_09_ins_01_needs_a_complete_previous_period_and_is_exact_at_the_edge() -> None:
    cats = [CategoryDelta("transport", "Transport", D("150000"), D("100000"))]  # +50%, +50.000
    assert len(ins_01(facts(categories=cats), CFG)) == 1
    assert ins_01(facts(categories=cats, previous_complete=False), CFG) == []
    edge = [CategoryDelta("transport", "Transport", D("150000"), D("100000"))]
    assert ins_01(facts(categories=edge), CFG)[0].message == (
        "Your Transport spending is up 50% compared with the same point last period"
    )


def test_fr_09_ins_02_weekend_ratio_and_weekend_count() -> None:
    w = WeekendFacts(D("1300"), 10, D("1000"), 10, 4)  # 130 / 100 = 1.3 exactly
    out = ins_02(facts(weekend=w), CFG)
    assert (
        len(out) == 1
        and out[0].message == "You spend 1.3× more per day on weekends than on weekdays"
    )
    assert ins_02(facts(weekend=WeekendFacts(D("1299"), 10, D("1000"), 10, 4)), CFG) == []
    assert ins_02(facts(weekend=WeekendFacts(D("2000"), 10, D("1000"), 10, 3)), CFG) == []
    assert ins_02(facts(weekend=WeekendFacts(D("2000"), 10, D("0"), 10, 8)), CFG) == []
    assert ins_02(facts(weekend=None), CFG) == []


def test_fr_09_ins_03_recurring_share() -> None:
    f = facts(
        recurring_count=2, recurring_monthly=D("1000000"), average_monthly_expenses=D("10000000")
    )
    out = ins_03(f, CFG)
    assert (
        out[0].message == "Recurring payments make up 10% of your monthly spending (≈Rp1.000.000)"
    )
    under = facts(
        recurring_count=2, recurring_monthly=D("999999"), average_monthly_expenses=D("10000000")
    )
    assert ins_03(under, CFG) == []
    assert (
        ins_03(facts(recurring_count=0, recurring_monthly=D(0), average_monthly_expenses=D(1)), CFG)
        == []
    )
    assert (
        ins_03(facts(recurring_count=1, recurring_monthly=D(1), average_monthly_expenses=None), CFG)
        == []
    )


def test_fr_09_ins_04_only_medium_and_high_bands_warn() -> None:
    budgets = [
        BudgetPace(None, "Overall", D("5000000"), D("5600000"), "high"),
        BudgetPace("food_beverage", "Food & Beverage", D("1000000"), D("1100000"), "medium"),
        BudgetPace("transport", "Transport", D("1000000"), D("700000"), "low"),
    ]
    out = ins_04(facts(budgets=budgets), CFG)
    assert [c.subject_key for c in out] == ["overall", "food_beverage"]
    assert (
        out[0].message
        == "At your current pace, you may exceed your Overall budget by about Rp600.000"
    )
    assert all(c.severity == "warning" for c in out)


def test_fr_09_ins_05_top_merchant_share_and_count() -> None:
    top = ("gojek", "Gojek", D("150000"), 5)
    assert len(ins_05(facts(top_merchant=top, period_expenses=D("1000000")), CFG)) == 1  # 15%, 5 tx
    assert ins_05(facts(top_merchant=top, period_expenses=D("1000001")), CFG) == []
    assert (
        ins_05(
            facts(top_merchant=("gojek", "Gojek", D("150000"), 4), period_expenses=D("1000000")),
            CFG,
        )
        == []
    )
    assert ins_05(facts(top_merchant=None, period_expenses=D("1")), CFG) == []


def test_fr_09_ins_06_small_purchases() -> None:
    f = facts(small_count=15, small_sum=D("100000"), period_expenses=D("1000000"))
    out = ins_06(f, CFG)
    assert out[0].message == "15 small purchases under Rp25.000 added up to Rp100.000 this period"
    assert (
        ins_06(facts(small_count=14, small_sum=D("100000"), period_expenses=D("1000000")), CFG)
        == []
    )
    assert (
        ins_06(facts(small_count=15, small_sum=D("99999"), period_expenses=D("1000000")), CFG) == []
    )


@pytest.mark.parametrize(
    ("income", "expenses", "severity", "pct"),
    [
        ("10000000", "9000000", "positive", 10),
        ("10000000", "9100000", "info", 9),
        ("10000000", "10000000", "info", 0),
        ("10000000", "10500000", "warning", -5),
    ],
)
def test_fr_09_ins_07_savings_rate(income: str, expenses: str, severity: str, pct: int) -> None:
    out = ins_07(facts(previous_income=D(income), previous_expenses=D(expenses)), CFG)
    assert out[0].severity == severity and out[0].message_params["pct"] == str(pct)
    assert out[0].evidence["period"] == {"start": "2026-10-01", "end": "2026-10-31"}


def test_fr_09_ins_07_needs_income_and_a_complete_previous_period() -> None:
    assert ins_07(facts(previous_income=D(0), previous_expenses=D(5)), CFG) == []
    assert (
        ins_07(facts(previous_income=D(5), previous_expenses=D(1), previous_complete=False), CFG)
        == []
    )


def test_fr_09_ins_08_price_change_wording_and_severity() -> None:
    up = ins_08(
        facts(price_changes=[PriceChange("netflix", "Netflix", D("54000"), D("65000"))]), CFG
    )
    assert up[0].message == "Netflix charged Rp65.000 this time, up from Rp54.000"
    assert up[0].severity == "warning" and up[0].subject_key == "netflix"
    down = ins_08(
        facts(price_changes=[PriceChange("netflix", "Netflix", D("65000"), D("54000"))]), CFG
    )
    assert down[0].severity == "info" and "down from" in down[0].message


def test_fr_09_ins_09_review_queue() -> None:
    assert ins_09(facts(review_queue=4), CFG) == []
    out = ins_09(facts(review_queue=5), CFG)
    assert out[0].message.startswith("5 transactions need a category")


def test_fr_09_priority_orders_warning_then_positive_then_info_then_magnitude() -> None:
    f = facts(
        categories=[
            CategoryDelta("a", "A", D("1000000"), D("500000")),  # up 100%: warning
            CategoryDelta("b", "B", D("100000"), D("500000")),  # down 80%: positive
        ],
        review_queue=900,  # info with a huge magnitude
    )
    ordered = sorted(evaluate(f, CFG), key=lambda c: c.priority, reverse=True)
    assert [c.severity for c in ordered] == ["warning", "positive", "info"]
    assert ordered[2].priority < D("2000")  # magnitude never lifts info above positive


def test_fr_09_evidence_reproduces_the_message() -> None:
    cats = [CategoryDelta("transport", "Transport", D("250000"), D("200000"))]
    c = ins_01(facts(categories=cats), CFG)[0]
    m = c.evidence["metrics"]
    pct = (D(m["current_to_date"]) - D(m["previous_same_days"])) / D(m["previous_same_days"]) * 100
    assert str(whole(pct)) == c.message_params["pct"]
    assert c.evidence["rule_id"] == "INS-01" and c.evidence["period"]["start"] == "2026-11-01"
    assert all(
        isinstance(v, str) for v in m.values() if not isinstance(v, int)
    )  # money is a string
