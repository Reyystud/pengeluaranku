"""Rule-based recurring series detector (PRD 7.8, FR-08). Pure functions, no I/O.

Input is one user's transactions as ``Occurrence`` rows (local dates); output is the series that
pass the rules in 7.8 steps 1-8. Amounts stay ``Decimal``; the coefficient of variation is a
ratio computed in floats and stored with 4 decimals. Nothing here logs or prints transaction data.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ml.recurring.config import Frequency, RecurringConfig

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Occurrence:
    transaction_id: str
    merchant_key: str
    merchant_display: str
    transaction_type: str  # income | expense
    category_id: str
    day: date
    amount: Decimal


@dataclass(frozen=True)
class AmountChange:
    previous_amount: Decimal
    latest_amount: Decimal


@dataclass(frozen=True)
class DetectedSeries:
    merchant_key: str
    merchant_display: str
    transaction_type: str
    category_id: str
    frequency: str
    median_interval_days: Decimal
    expected_amount: Decimal
    amount_cv: Decimal
    last_date: date
    next_expected_date: date
    occurrences: int
    confidence: Decimal
    status: str  # active | paused | ended (user statuses are applied by the service)
    transaction_ids: tuple[str, ...]
    amount_change: AmountChange | None


def monthly_equivalent(amount: Decimal, frequency: Frequency) -> Decimal:
    """Step 8: weekly x 52/12, biweekly x 26/12, monthly x 1, quarterly / 3, yearly / 12."""
    return (amount * frequency.per_year / 12).quantize(CENT, rounding=ROUND_HALF_UP)


def _median_amount(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    middle = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return middle.quantize(CENT, rounding=ROUND_HALF_UP)


def _round_days(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def match_frequency(median_interval: float, cfg: RecurringConfig) -> Frequency | None:
    """Step 3: the frequency whose window contains the median interval."""
    for f in cfg.frequencies:
        if f.min_days <= median_interval <= f.max_days:
            return f
    return None


def series_status(
    today: date,
    next_expected: date,
    median_interval: float,
    frequency: Frequency,
    cfg: RecurringConfig,
) -> str:
    """Step 7: paused once overdue beyond the tolerance, ended after 2 intervals overdue."""
    overdue = (today - next_expected).days
    if overdue > cfg.ended_after_intervals * median_interval:
        return "ended"
    if overdue > frequency.tolerance_days:
        return "paused"
    return "active"


def amount_change(amounts: Sequence[Decimal], cfg: RecurringConfig) -> AmountChange | None:
    """FR-08.03: the latest amount against the median of the (up to 3) occurrences before it."""
    if len(amounts) < 3:
        return None
    previous = _median_amount(amounts[-4:-1])
    latest = amounts[-1]
    diff = abs(latest - previous)
    if diff >= cfg.change_min_amount and diff > previous * cfg.change_pct:
        return AmountChange(previous_amount=previous, latest_amount=latest)
    return None


def _merge_same_day(rows: Sequence[Occurrence]) -> list[tuple[Occurrence, list[str]]]:
    """Step 2: one occurrence per day (the first by transaction id); all its ids stay linked."""
    by_day: dict[date, list[Occurrence]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (r.day, r.transaction_id)):
        by_day[row.day].append(row)
    return [(group[0], [r.transaction_id for r in group]) for _, group in sorted(by_day.items())]


def _detect_group(
    rows: Sequence[Occurrence], today: date, cfg: RecurringConfig
) -> DetectedSeries | None:
    """Steps 2-7 on the whole merchant group, then on amount clusters when the group fails.

    A merchant can be both a bill and an ordinary shop (a utility plus top-ups, a landlord plus
    one-off payments). The rules of 7.8 then see mixed intervals and reject the group, so the
    same rules are retried on the rows near one amount, largest cluster first. Rows outside the
    winning cluster are not linked to the series and stay non-recurring.
    """
    whole = _detect_rows(rows, today, cfg)
    if whole is not None:
        return whole
    merged = _merge_same_day(rows)
    if len(merged) <= cfg.min_occurrences:
        return None
    clusters: dict[frozenset[str], list[Occurrence]] = {}
    for anchor in sorted({occ.amount for occ, _ in merged}):
        members = [r for r in rows if abs(r.amount - anchor) <= anchor * cfg.cluster_tolerance]
        if cfg.cluster_min_share * len(rows) <= len(members) < len(rows):  # whole group: tried
            clusters[frozenset(r.transaction_id for r in members)] = members
    ranked = sorted(clusters.values(), key=lambda c: (-len(c), min(r.transaction_id for r in c)))
    for members in ranked[: cfg.cluster_candidates]:
        found = _detect_rows(members, today, cfg)
        if found is not None:
            return found
    return None


def _detect_rows(
    rows: Sequence[Occurrence], today: date, cfg: RecurringConfig
) -> DetectedSeries | None:
    merged = _merge_same_day(rows)
    if len(merged) < cfg.min_occurrences:
        return None
    days = [occ.day for occ, _ in merged]
    intervals = [(b - a).days for a, b in zip(days, days[1:], strict=False)]
    median_interval = float(statistics.median(intervals))
    frequency = match_frequency(median_interval, cfg)
    if frequency is None:
        return None
    inside = sum(1 for i in intervals if frequency.min_days <= i <= frequency.max_days)
    regularity = inside / len(intervals)
    if regularity < cfg.min_regularity:
        return None

    amounts = [occ.amount for occ, _ in merged]
    mean = float(sum(amounts) / len(amounts))
    cv = statistics.pstdev([float(a) for a in amounts]) / mean if mean > 0 else 0.0
    stable = cv <= cfg.max_cv
    if not stable and frequency.name != "weekly":
        return None
    confidence = (
        regularity
        * min(1.0, len(merged) / cfg.occurrences_saturate)
        * (1.0 if stable else cfg.cv_penalty)
    )
    if confidence < cfg.show_min:
        return None

    last = merged[-1][0]
    next_expected = last.day + timedelta(days=_round_days(median_interval))
    category = _modal_category(merged)
    return DetectedSeries(
        merchant_key=last.merchant_key,
        merchant_display=last.merchant_display,
        transaction_type=last.transaction_type,
        category_id=category,
        frequency=frequency.name,
        median_interval_days=Decimal(str(median_interval)).quantize(CENT),
        expected_amount=_median_amount(amounts[-3:]),
        amount_cv=Decimal(str(cv)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        last_date=last.day,
        next_expected_date=next_expected,
        occurrences=len(merged),
        confidence=Decimal(str(confidence)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
        status=series_status(today, next_expected, median_interval, frequency, cfg),
        transaction_ids=tuple(tid for _, ids in merged for tid in ids),
        amount_change=amount_change(amounts, cfg),
    )


def _modal_category(merged: Sequence[tuple[Occurrence, list[str]]]) -> str:
    """Most common category of the series; ties go to the one used most recently."""
    counts = Counter(occ.category_id for occ, _ in merged)
    latest = {occ.category_id: occ.day for occ, _ in merged}
    return max(counts, key=lambda c: (counts[c], latest[c]))


def detect(
    occurrences: Iterable[Occurrence], today: date, cfg: RecurringConfig
) -> list[DetectedSeries]:
    """Steps 1-8 over one user's transactions. Returned in ``next_expected_date`` order."""
    since = today - timedelta(days=cfg.lookback_days)
    groups: dict[tuple[str, str], list[Occurrence]] = defaultdict(list)
    for occ in occurrences:
        if (
            occ.merchant_key
            and since <= occ.day <= today
            and occ.transaction_type
            in (
                "income",
                "expense",
            )
        ):
            groups[(occ.merchant_key, occ.transaction_type)].append(occ)
    found = [s for rows in groups.values() if (s := _detect_group(rows, today, cfg)) is not None]
    return sorted(found, key=lambda s: (s.next_expected_date, s.merchant_key, s.transaction_type))


def expected_dates(
    next_expected: date, interval_days: int, status: str, today: date, period_end: date
) -> list[date]:
    """Occurrences still expected from ``today`` to ``period_end`` (7.7.1, generalised).

    ``status`` is the automatic status (``series_status``); a user-confirmed series is judged by it
    too, so a confirmed series that stopped paying is not projected. A series that is active but a
    few days late counts once, today. Weekly series can contribute several dates in one period.
    Paused and ended series contribute nothing.
    """
    if status != "active" or interval_days <= 0:
        return []
    nxt = max(next_expected, today)
    dates: list[date] = []
    while nxt <= period_end:
        dates.append(nxt)
        nxt += timedelta(days=interval_days)
    return dates
