"""Recurring detector (PRD 7.8): algorithm steps, statuses, amount change, expectations."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ml.recurring import (
    Occurrence,
    amount_change,
    detect,
    expected_dates,
    load_recurring_config,
    match_frequency,
    monthly_equivalent,
    series_status,
)

CFG = load_recurring_config()
TODAY = date(2026, 11, 21)


def rows(
    key: str,
    days: list[date],
    amounts: list[str] | str = "100000",
    *,
    kind: str = "expense",
    category: str = "cat-a",
) -> list[Occurrence]:
    values = amounts if isinstance(amounts, list) else [amounts] * len(days)
    return [
        Occurrence(f"{key}-{i}", key, key.title(), kind, category, d, Decimal(v))
        for i, (d, v) in enumerate(zip(days, values, strict=True))
    ]


def every(n: int, count: int, last: date = TODAY - timedelta(days=3)) -> list[date]:
    return [last - timedelta(days=n * k) for k in range(count - 1, -1, -1)]


def monthly(count: int, day: int = 5, jitter: int = 0) -> list[date]:
    out: list[date] = []
    year, month = 2026, 11 - count + 1
    for k in range(count):
        m = month + k
        out.append(
            date(year + (m - 1) // 12, (m - 1) % 12 + 1, day) + timedelta(days=jitter * (k % 3))
        )
    return out


# ---- steps 1-6 -----------------------------------------------------------------------------


def test_fr_08_01_monthly_series_is_detected_with_its_fields() -> None:
    found = detect(rows("netflix", monthly(6, day=5), "54000"), TODAY, CFG)
    assert len(found) == 1
    s = found[0]
    assert (s.frequency, s.transaction_type, s.occurrences) == ("monthly", "expense", 6)
    assert s.expected_amount == Decimal("54000.00")
    assert s.amount_cv == Decimal("0.0000")
    assert s.last_date == date(2026, 11, 5)
    assert s.next_expected_date == s.last_date + timedelta(days=int(s.median_interval_days))
    assert s.status == "active"
    assert s.confidence == Decimal("1.000")


@pytest.mark.parametrize(
    ("step", "frequency"),
    [(7, "weekly"), (14, "biweekly"), (30, "monthly"), (91, "quarterly")],
)
def test_fr_08_02_each_frequency_is_matched(step: int, frequency: str) -> None:
    found = detect(rows("m", every(step, 5)), TODAY, CFG)
    assert [s.frequency for s in found] == [frequency]


def test_fr_08_01_income_series_is_detected_and_transfers_are_ignored() -> None:
    income = rows("gaji", monthly(5, day=25), "8000000", kind="income", category="salary")
    transfer = rows("tabungan", monthly(5, day=26), "500000", kind="transfer")
    found = detect(income + transfer, TODAY, CFG)
    assert [(s.merchant_key, s.transaction_type) for s in found] == [("gaji", "income")]


def test_fr_08_01_same_merchant_as_income_and_expense_gives_two_series() -> None:
    both = rows("x", monthly(5)) + rows("x", monthly(5, day=20), kind="income")
    found = detect(both, TODAY, CFG)
    assert sorted(s.transaction_type for s in found) == ["expense", "income"]


def test_step1_fewer_than_three_occurrences_and_empty_keys_are_skipped() -> None:
    assert detect(rows("two", monthly(2)), TODAY, CFG) == []
    assert detect(rows("", monthly(5)), TODAY, CFG) == []


def test_step1_occurrences_outside_the_lookback_window_do_not_count() -> None:
    old = [TODAY - timedelta(days=CFG.lookback_days + 30 * k) for k in range(5)]
    assert detect(rows("old", old), TODAY, CFG) == []
    future = [TODAY + timedelta(days=30 * k) for k in range(1, 5)]
    assert detect(rows("future", future), TODAY, CFG) == []


def test_step2_same_day_duplicates_are_merged_but_stay_linked() -> None:
    days = monthly(4)
    data = rows("dup", days) + [
        Occurrence("dup-extra", "dup", "Dup", "expense", "cat-a", days[1], Decimal("100000"))
    ]
    (s,) = detect(data, TODAY, CFG)
    assert s.occurrences == 4
    assert len(s.transaction_ids) == 5 and "dup-extra" in s.transaction_ids


def test_step4_irregular_intervals_are_rejected() -> None:
    days = [TODAY - timedelta(days=d) for d in (3, 40, 47, 100, 104)][::-1]
    assert detect(rows("random", days), TODAY, CFG) == []


def test_step4_regularity_threshold_is_inclusive_at_0_7() -> None:
    # 10 occurrences, 9 intervals: 7 monthly (28-34) + 2 far outside gives regularity 7/9 = 0.78
    days = [date(2026, 1, 5)]
    for gap in (30, 30, 30, 30, 30, 30, 30, 10, 10):
        days.append(days[-1] + timedelta(days=gap))
    shifted = TODAY - days[-1]
    days = [d + shifted for d in days]
    (s,) = detect(rows("mostly", days), TODAY, CFG)
    assert s.frequency == "monthly"
    assert s.confidence == Decimal("0.778")


def test_step5_variable_monthly_amounts_are_rejected_but_weekly_survive_with_a_penalty() -> None:
    wild = ["10000", "300000", "20000", "500000", "15000", "250000"]
    assert detect(rows("var", monthly(6), wild), TODAY, CFG) == []
    (weekly,) = detect(rows("grab", every(7, 6), wild), TODAY, CFG)
    assert weekly.frequency == "weekly"
    assert weekly.confidence == Decimal("0.700")  # 1 x 1 x 0.7
    assert weekly.amount_cv > Decimal("0.25")


def test_step6_confidence_grows_with_occurrences() -> None:
    three = detect(rows("a", monthly(3)), TODAY, CFG)
    assert three[0].confidence == Decimal("0.750")  # 3 / 4
    assert detect(rows("b", monthly(4)), TODAY, CFG)[0].confidence == Decimal("1.000")


def test_step6_series_below_the_show_threshold_are_dropped() -> None:
    # weekly + high CV + 3 occurrences = 1 x 0.75 x 0.7 = 0.525 < 0.6
    wild = ["10000", "300000", "20000"]
    assert detect(rows("low", every(7, 3), wild), TODAY, CFG) == []


def test_step6_yearly_needs_three_hits_so_it_cannot_surface_in_400_days() -> None:
    assert detect(rows("annual", [date(2025, 11, 20), date(2024, 11, 20)]), TODAY, CFG) == []


def test_fr_08_02_expected_amount_is_the_median_of_the_last_three() -> None:
    amounts = ["50000", "52000", "54000", "55000", "60000"]
    (s,) = detect(rows("p", monthly(5), amounts), TODAY, CFG)
    assert s.expected_amount == Decimal("55000.00")


def test_fr_08_02_category_is_the_most_common_one() -> None:
    data = rows("mix", monthly(5), category="cat-a")
    data[-1] = Occurrence(
        "mix-x", "mix", "Mix", "expense", "cat-b", data[-1].day, Decimal("100000")
    )
    (s,) = detect(data, TODAY, CFG)
    assert s.category_id == "cat-a"


# ---- step 3 helper and step 7/8 ----------------------------------------------------------


def test_step3_frequency_windows() -> None:
    assert match_frequency(28, CFG).name == "monthly"  # type: ignore[union-attr]
    assert match_frequency(34, CFG).name == "monthly"  # type: ignore[union-attr]
    assert match_frequency(35, CFG) is None
    assert match_frequency(20, CFG) is None


@pytest.mark.parametrize(
    ("overdue", "status"),
    [(-5, "active"), (0, "active"), (4, "active"), (5, "paused"), (60, "paused"), (61, "ended")],
)
def test_step7_status_from_how_overdue_the_next_date_is(overdue: int, status: str) -> None:
    monthly_f = CFG.frequency("monthly")
    next_expected = TODAY - timedelta(days=overdue)
    assert series_status(TODAY, next_expected, 30.0, monthly_f, CFG) == status


def test_step7_detect_marks_a_stale_series_paused_or_ended() -> None:
    paused = rows("p", monthly(5), "10000")
    assert detect(paused, date(2026, 12, 20), CFG)[0].status == "paused"
    assert detect(paused, date(2027, 3, 1), CFG)[0].status == "ended"


@pytest.mark.parametrize(
    ("frequency", "amount", "expected"),
    [
        ("weekly", "120000", "520000.00"),
        ("biweekly", "120000", "260000.00"),
        ("monthly", "120000", "120000.00"),
        ("quarterly", "120000", "40000.00"),
        ("yearly", "120000", "10000.00"),
    ],
)
def test_step8_monthly_equivalent(frequency: str, amount: str, expected: str) -> None:
    assert monthly_equivalent(Decimal(amount), CFG.frequency(frequency)) == Decimal(expected)


# ---- FR-08.03 ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amounts", "changed"),
    [
        (["54000", "54000", "54000", "65000"], True),  # +20%, +11,000
        (["54000", "54000", "54000", "58000"], False),  # +7.4% and below Rp5.000 floor not both
        (["54000", "54000", "54000", "59000"], False),  # exactly 5,000 but 9.3% < 10%
        (["100000", "100000", "100000", "111000"], True),  # +11% and 11,000
        (["20000", "20000", "20000", "24000"], False),  # +20% but only Rp4.000
        (["54000", "54000"], False),  # not enough history
    ],
)
def test_fr_08_03_amount_change_needs_both_the_percentage_and_the_floor(
    amounts: list[str], changed: bool
) -> None:
    result = amount_change([Decimal(a) for a in amounts], CFG)
    assert (result is not None) is changed


def test_fr_08_03_detect_reports_previous_and_latest_amounts() -> None:
    amounts = ["54000", "54000", "54000", "65000"]
    (s,) = detect(rows("n", monthly(4), amounts), TODAY, CFG)
    assert s.amount_change is not None
    assert (s.amount_change.previous_amount, s.amount_change.latest_amount) == (
        Decimal("54000.00"),
        Decimal("65000"),
    )


# ---- 7.7.1 expectations --------------------------------------------------------------------


def test_expected_dates_monthly_inside_the_period() -> None:
    assert expected_dates(date(2026, 11, 25), 30, "active", TODAY, date(2026, 11, 30)) == [
        date(2026, 11, 25)
    ]
    assert expected_dates(date(2026, 12, 25), 30, "active", TODAY, date(2026, 11, 30)) == []


def test_expected_dates_weekly_counts_every_remaining_occurrence() -> None:
    dates = expected_dates(date(2026, 11, 23), 7, "active", TODAY, date(2026, 12, 10))
    assert dates == [date(2026, 11, 23), date(2026, 11, 30), date(2026, 12, 7)]


def test_expected_dates_a_late_active_series_counts_once_today() -> None:
    assert expected_dates(date(2026, 11, 19), 30, "active", TODAY, date(2026, 11, 30)) == [TODAY]


@pytest.mark.parametrize("status", ["paused", "ended", "user_rejected"])
def test_expected_dates_ignore_series_that_are_not_active(status: str) -> None:
    assert expected_dates(date(2026, 11, 25), 30, status, TODAY, date(2026, 11, 30)) == []


# ---- properties ----------------------------------------------------------------------------


@given(
    st.lists(st.integers(min_value=0, max_value=399), min_size=0, max_size=30),
    st.lists(st.integers(min_value=1, max_value=5_000_000), min_size=30, max_size=30),
)
def test_detect_never_crashes_and_keeps_confidence_in_range(
    offsets: list[int], amounts: list[int]
) -> None:
    days = [TODAY - timedelta(days=o) for o in offsets]
    data = rows("k", days, [str(a) for a in amounts[: len(days)]])
    for s in detect(data, TODAY, CFG):
        assert Decimal("0.6") <= s.confidence <= Decimal("1")
        assert s.occurrences >= CFG.min_occurrences
        assert s.next_expected_date > s.last_date


# ---- merchant shared with ordinary purchases (decision: amount cluster retry) -----------------


def test_fr_08_01_a_bill_mixed_with_one_off_purchases_is_found_by_amount_cluster() -> None:
    bill = rows("pln", monthly(6, day=5), "350000")
    extras = [
        Occurrence(f"pln-x{i}", "pln", "Pln", "expense", "cat-a", d, Decimal(a))
        for i, (d, a) in enumerate(
            [
                (date(2026, 6, 17), "50000"),
                (date(2026, 7, 29), "100000"),
                (date(2026, 9, 12), "20000"),
            ]
        )
    ]
    (s,) = detect(bill + extras, TODAY, CFG)
    assert s.occurrences == 6 and s.expected_amount == Decimal("350000.00")
    assert not any(t.startswith("pln-x") for t in s.transaction_ids)  # one-offs stay non-recurring


def test_cluster_retry_ignores_a_small_regular_subset_of_a_busy_merchant() -> None:
    # 30 visits at varied amounts; 4 of them happen to be 30 days apart with the same amount
    busy = [
        Occurrence(
            f"b{i}", "kopi", "Kopi", "expense", "c", TODAY - timedelta(days=3 * i), Decimal(a)
        )
        for i, a in enumerate([15000, 22000, 31000, 47000, 18000, 26000] * 5)
    ]
    assert detect(busy, TODAY, CFG) == []


def test_cluster_retry_needs_a_dominant_cluster() -> None:
    cfg = CFG
    share = cfg.cluster_min_share
    # 5 rows near one amount out of 14 is below the 50% share
    regular = rows("mix", monthly(5), "100000")
    noise = [
        Occurrence(
            f"mix-n{i}",
            "mix",
            "Mix",
            "expense",
            "cat-a",
            TODAY - timedelta(days=9 * i + 2),
            Decimal(str(40000 + 17000 * i)),
        )
        for i in range(9)
    ]
    assert share == Decimal("0.5")
    assert detect(regular + noise, TODAY, cfg) == []
