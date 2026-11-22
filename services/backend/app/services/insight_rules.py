"""Insight rules INS-01 to INS-09 (PRD 7.9): pure functions from ``Facts`` to candidates.

No database and no clock in here: the service gathers the facts, these functions decide. Every
candidate carries the numbers it was computed from in ``evidence`` (FR-09.02), so a stored insight
can be re-derived from its own payload. Money stays ``Decimal`` and is a string in JSON.

Priority (FR-09.05): ``weight * 1000 + magnitude`` with weight warning 3, positive 2, info 1 and a
rule-specific magnitude capped below 1000, so severity decides first and magnitude second.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.insight_config import InsightConfig

SEVERITY_WEIGHT = {"warning": 3, "positive": 2, "info": 1}
MAX_MAGNITUDE = Decimal("999.9999")
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class CategoryDelta:
    slug: str
    name: str
    current: Decimal
    previous: Decimal


@dataclass(frozen=True)
class WeekendFacts:
    weekend_total: Decimal
    weekend_days: int
    weekday_total: Decimal
    weekday_days: int
    weekends_with_data: int


@dataclass(frozen=True)
class BudgetPace:
    slug: str | None
    name: str
    limit: Decimal
    predicted_total: Decimal
    band: str  # low | medium | high


@dataclass(frozen=True)
class PriceChange:
    merchant_key: str
    display: str
    previous: Decimal
    latest: Decimal


@dataclass(frozen=True)
class Facts:
    period_start: dt.date
    period_end: dt.date
    previous_start: dt.date
    previous_end: dt.date
    elapsed_days: int
    previous_complete: bool
    categories: list[CategoryDelta] = field(default_factory=list)
    weekend: WeekendFacts | None = None
    recurring_monthly: Decimal = Decimal(0)
    recurring_count: int = 0
    average_monthly_expenses: Decimal | None = None
    budgets: list[BudgetPace] = field(default_factory=list)
    top_merchant: tuple[str, str, Decimal, int] | None = None  # key, display, amount, count
    period_expenses: Decimal = Decimal(0)
    small_count: int = 0
    small_sum: Decimal = Decimal(0)
    previous_income: Decimal = Decimal(0)
    previous_expenses: Decimal = Decimal(0)
    price_changes: list[PriceChange] = field(default_factory=list)
    review_queue: int = 0


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    rule_version: str
    subject_key: str
    severity: str
    magnitude: Decimal
    title: str
    message: str
    message_key: str
    message_params: dict[str, str]
    evidence: dict[str, Any]

    @property
    def priority(self) -> Decimal:
        capped = min(max(self.magnitude, Decimal(0)), MAX_MAGNITUDE)
        return (Decimal(SEVERITY_WEIGHT[self.severity]) * 1000 + capped).quantize(Decimal("0.0001"))


# -- formatting ----------------------------------------------------------------------------------
def whole(value: Decimal) -> int:
    """Percentages are integers (PRD 7.9): half up, away from zero for negatives."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def idr(value: Decimal) -> str:
    """``Rp1.250.000``: whole rupiah with dots as thousands separators."""
    rounded = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return ("-" if rounded < 0 else "") + "Rp" + f"{abs(rounded):,}".replace(",", ".")


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def _period(facts: Facts) -> dict[str, str]:
    return {"start": facts.period_start.isoformat(), "end": facts.period_end.isoformat()}


def _previous(facts: Facts) -> dict[str, str]:
    return {"start": facts.previous_start.isoformat(), "end": facts.previous_end.isoformat()}


def _make(
    cfg: InsightConfig,
    rule_id: str,
    subject: str,
    severity: str,
    magnitude: Decimal,
    title: str,
    message: str,
    variant: str,
    params: dict[str, str],
    evidence: dict[str, Any],
) -> Candidate:
    return Candidate(
        rule_id=rule_id,
        rule_version=cfg.rule_version(rule_id),
        subject_key=subject,
        severity=severity,
        magnitude=magnitude,
        title=title,
        message=message,
        message_key=f"insights.{rule_id.lower()}.{variant}",
        message_params=params,
        evidence={"rule_id": rule_id, **evidence},
    )


# -- rules ---------------------------------------------------------------------------------------
def ins_01(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    """Category change: current period to date against the same number of days last period."""
    rule = "INS-01"
    if not facts.previous_complete:
        return []
    min_pct, min_delta = cfg.number(rule, "min_abs_pct"), cfg.number(rule, "min_abs_delta")
    min_prev = cfg.number(rule, "min_previous")
    out = []
    for c in facts.categories:
        if c.previous < min_prev:
            continue
        delta = c.current - c.previous
        pct = delta / c.previous * HUNDRED
        if abs(pct) < min_pct or abs(delta) < min_delta:
            continue
        direction = "up" if delta > 0 else "down"
        shown = abs(whole(pct))
        out.append(
            _make(
                cfg,
                rule,
                c.slug,
                "warning" if delta > 0 else "positive",
                abs(pct),
                f"{c.name} spending {direction}",
                f"Your {c.name} spending is {direction} {shown}% compared with the same point "
                "last period",
                direction,
                {"category": c.name, "direction": direction, "pct": str(shown)},
                {
                    "metrics": {
                        "current_to_date": money(c.current),
                        "previous_same_days": money(c.previous),
                        "delta": money(delta),
                        "delta_pct": str(pct.quantize(Decimal("0.01"))),
                    },
                    "period": _period(facts),
                    "previous_period": _previous(facts),
                    "days_compared": facts.elapsed_days,
                    "filters": {"category": c.slug, "transaction_type": "expense"},
                },
            )
        )
    return out


def ins_02(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-02"
    w = facts.weekend
    if w is None or w.weekends_with_data < cfg.number(rule, "min_weekends_with_data"):
        return []
    if w.weekend_days == 0 or w.weekday_days == 0:
        return []
    weekend_avg = w.weekend_total / w.weekend_days
    weekday_avg = w.weekday_total / w.weekday_days
    if weekday_avg <= 0:
        return []
    ratio = weekend_avg / weekday_avg
    if ratio < cfg.number(rule, "min_ratio"):
        return []
    shown = ratio.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return [
        _make(
            cfg,
            rule,
            "",
            "info",
            ratio * HUNDRED,
            "Weekends cost more",
            f"You spend {shown}× more per day on weekends than on weekdays",
            "ratio",
            {"ratio": str(shown)},
            {
                "metrics": {
                    "weekend_daily_average": money(weekend_avg),
                    "weekday_daily_average": money(weekday_avg),
                    "ratio": str(ratio.quantize(Decimal("0.0001"))),
                    "weekend_days": w.weekend_days,
                    "weekday_days": w.weekday_days,
                    "weekends_with_data": w.weekends_with_data,
                },
                "period": _period(facts),
                "filters": {"transaction_type": "expense", "weeks": int(cfg.number(rule, "weeks"))},
            },
        )
    ]


def ins_03(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-03"
    average = facts.average_monthly_expenses
    if facts.recurring_count == 0 or average is None or average <= 0:
        return []
    share = facts.recurring_monthly / average * HUNDRED
    if share < cfg.number(rule, "min_share_pct"):
        return []
    return [
        _make(
            cfg,
            rule,
            "",
            "info",
            share,
            "Recurring payments",
            f"Recurring payments make up {whole(share)}% of your monthly spending "
            f"(≈{idr(facts.recurring_monthly)})",
            "share",
            {"pct": str(whole(share)), "amount": idr(facts.recurring_monthly)},
            {
                "metrics": {
                    "recurring_monthly_equivalent": money(facts.recurring_monthly),
                    "average_monthly_expenses": money(average),
                    "share_pct": str(share.quantize(Decimal("0.01"))),
                    "recurring_series": facts.recurring_count,
                },
                "period": _period(facts),
                "filters": {
                    "transaction_type": "expense",
                    "periods": int(cfg.number(rule, "periods")),
                },
            },
        )
    ]


def ins_04(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-04"
    out = []
    for b in facts.budgets:
        if b.band not in ("medium", "high"):
            continue
        over = b.predicted_total - b.limit
        if over <= 0:
            over = Decimal(0)
        out.append(
            _make(
                cfg,
                rule,
                b.slug or "overall",
                "warning",
                over / b.limit * HUNDRED if b.limit > 0 else Decimal(0),
                f"{b.name} budget pace",
                f"At your current pace, you may exceed your {b.name} budget by about {idr(over)}",
                "may_exceed",
                {"budget": b.name, "amount": idr(over)},
                {
                    "metrics": {
                        "limit": money(b.limit),
                        "predicted_total": money(b.predicted_total),
                        "predicted_over_budget": money(b.predicted_total - b.limit),
                        "exceed_band": b.band,
                    },
                    "period": _period(facts),
                    "filters": {"category": b.slug},
                },
            )
        )
    return out


def ins_05(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-05"
    top = facts.top_merchant
    if top is None or facts.period_expenses <= 0:
        return []
    key, display, amount, count = top
    share = amount / facts.period_expenses * HUNDRED
    if share < cfg.number(rule, "min_share_pct") or count < cfg.number(rule, "min_transactions"):
        return []
    return [
        _make(
            cfg,
            rule,
            key,
            "info",
            share,
            "Top merchant",
            f"{display} accounts for {whole(share)}% of your spending this period "
            f"({count} transactions)",
            "share",
            {"merchant": display, "pct": str(whole(share)), "count": str(count)},
            {
                "metrics": {
                    "merchant_total": money(amount),
                    "period_expenses": money(facts.period_expenses),
                    "share_pct": str(share.quantize(Decimal("0.01"))),
                    "transactions": count,
                },
                "period": _period(facts),
                "filters": {"merchant_key": key, "transaction_type": "expense"},
            },
        )
    ]


def ins_06(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-06"
    if facts.period_expenses <= 0:
        return []
    share = facts.small_sum / facts.period_expenses * HUNDRED
    if facts.small_count < cfg.number(rule, "min_count") or share < cfg.number(
        rule, "min_share_pct"
    ):
        return []
    below = cfg.number(rule, "below")
    return [
        _make(
            cfg,
            rule,
            "",
            "info",
            share,
            "Small purchases add up",
            f"{facts.small_count} small purchases under {idr(below)} added up to "
            f"{idr(facts.small_sum)} this period",
            "total",
            {"count": str(facts.small_count), "limit": idr(below), "amount": idr(facts.small_sum)},
            {
                "metrics": {
                    "small_count": facts.small_count,
                    "small_total": money(facts.small_sum),
                    "period_expenses": money(facts.period_expenses),
                    "share_pct": str(share.quantize(Decimal("0.01"))),
                },
                "period": _period(facts),
                "filters": {"transaction_type": "expense", "amount_below": money(below)},
            },
        )
    ]


def ins_07(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-07"
    if not facts.previous_complete or facts.previous_income <= 0:
        return []
    saved = facts.previous_income - facts.previous_expenses
    rate = saved / facts.previous_income * HUNDRED
    positive_at = cfg.number(rule, "positive_at_pct")
    severity = "warning" if rate < 0 else "positive" if rate >= positive_at else "info"
    return [
        _make(
            cfg,
            rule,
            "",
            severity,
            abs(rate),
            "Savings rate",
            f"You saved {whole(rate)}% of your income last period",
            "saved",
            {"pct": str(whole(rate))},
            {
                "metrics": {
                    "income": money(facts.previous_income),
                    "expenses": money(facts.previous_expenses),
                    "saved": money(saved),
                    "savings_rate_pct": str(rate.quantize(Decimal("0.01"))),
                },
                "period": _previous(facts),
                "filters": {"transfers": "excluded"},
            },
        )
    ]


def ins_08(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-08"
    out = []
    for p in facts.price_changes:
        if p.previous <= 0:
            continue
        pct = (p.latest - p.previous) / p.previous * HUNDRED
        out.append(
            _make(
                cfg,
                rule,
                p.merchant_key,
                "warning" if p.latest > p.previous else "info",
                abs(pct),
                f"{p.display} price change",
                f"{p.display} charged {idr(p.latest)} this time, up from {idr(p.previous)}"
                if p.latest > p.previous
                else f"{p.display} charged {idr(p.latest)} this time, down from {idr(p.previous)}",
                "up" if p.latest > p.previous else "down",
                {"merchant": p.display, "new": idr(p.latest), "old": idr(p.previous)},
                {
                    "metrics": {
                        "previous_amount": money(p.previous),
                        "latest_amount": money(p.latest),
                        "change_pct": str(pct.quantize(Decimal("0.01"))),
                    },
                    "period": _period(facts),
                    "filters": {"merchant_key": p.merchant_key, "source": "recurring_series"},
                },
            )
        )
    return out


def ins_09(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    rule = "INS-09"
    if facts.review_queue < cfg.number(rule, "min_queue"):
        return []
    n = facts.review_queue
    return [
        _make(
            cfg,
            rule,
            "",
            "info",
            Decimal(n),
            "Transactions need a category",
            f"{n} transactions need a category — reviewing them improves your insights",
            "queue",
            {"n": str(n)},
            {
                "metrics": {"review_queue": n},
                "period": _period(facts),
                "filters": {"category_status": ["suggested", "needs_review"]},
            },
        )
    ]


RULES = (ins_01, ins_02, ins_03, ins_04, ins_05, ins_06, ins_07, ins_08, ins_09)


def evaluate(facts: Facts, cfg: InsightConfig) -> list[Candidate]:
    return [c for rule in RULES for c in rule(facts, cfg)]
