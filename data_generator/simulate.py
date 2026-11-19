"""Per-user simulation of the synthetic ledger (PRD 10.1).

Every user is simulated from an independent RNG ``default_rng([seed, user_index])``, so the
output does not depend on worker count or user order.
"""

from __future__ import annotations

import calendar
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np

from data_generator import noise
from data_generator.config import Archetype, GeneratorConfig
from ml.config import Merchant, load_holidays
from ml.schemas.synthetic import MAX_TRANSACTION_AMOUNT

_NAMESPACE = uuid.UUID("6f1c2b1e-8a35-4c8e-9d3b-5a7e1f0c9a11")
_MAX_AMOUNT = int(MAX_TRANSACTION_AMOUNT)
_DEFAULT_AMOUNT = {"median": 50_000.0, "sigma": 0.6}
# Average rows produced per anomaly event, used to size the event count.
_ROWS_PER_EVENT = {
    "amount_spike": 1.0,
    "frequency_burst": 6.0,
    "new_merchant_high_value": 1.0,
    "category_surge": 8.0,
}


class Weighted:
    """Weighted index sampler (cumulative-probability lookup)."""

    def __init__(self, weights: list[float] | np.ndarray[Any, Any]) -> None:
        w = np.asarray(weights, dtype=float)
        self.cum = np.cumsum(w / w.sum())

    def draw(self, rng: np.random.Generator) -> int:
        return min(int(np.searchsorted(self.cum, rng.random(), side="right")), len(self.cum) - 1)


def _add_months(start: date, months: int) -> date:
    index = start.month - 1 + months
    return date(start.year + index // 12, index % 12 + 1, 1)


def round_amount(value: float) -> int:
    """Round to the nearest Rp500 (min Rp1.000, capped at the maximum transaction amount)."""
    return min(_MAX_AMOUNT, max(1000, int(round(value / 500.0)) * 500))


class Catalog:
    """Read-only lookup tables derived from the config, built once per process."""

    def __init__(self, cfg: GeneratorConfig) -> None:
        p = cfg.params
        self.start = cfg.start_date
        self.end = _add_months(cfg.start_date, cfg.months)  # exclusive
        self.days = [self.start + timedelta(days=i) for i in range((self.end - self.start).days)]
        self.months = [_add_months(self.start, i) for i in range(cfg.months)]

        self.by_category: dict[str, list[Merchant]] = {}
        for m in cfg.merchants:
            self.by_category.setdefault(m.category, []).append(m)
        self.weighted = {c: Weighted([m.weight for m in ms]) for c, ms in self.by_category.items()}

        self.amounts: dict[str, dict[str, float]] = {
            c: {"median": float(v["median"]), "sigma": float(v["sigma"])}
            for c, v in p["amounts"].items()
        }
        self.hours = {
            c: (
                [(float(h[0]), float(h[1])) for h in comps],
                Weighted([float(h[2]) for h in comps]),
            )
            for c, comps in p["hours"].items()
        }
        self.methods = {
            c: (list(probs), Weighted(list(probs.values())))
            for c, probs in p["payment_methods"].items()
        }
        _, holidays = load_holidays()
        self.holidays = {h.day for h in holidays} if p["calendar_effects"] else set()
        self.boost = {
            str(k): float(v) for k, v in p["category_boost_on_weekend_or_holiday"].items()
        }

    def amount_params(self, category: str) -> dict[str, float]:
        return self.amounts.get(category, _DEFAULT_AMOUNT)

    def hour_profile(self, category: str) -> tuple[list[tuple[float, float]], Weighted]:
        return self.hours.get(category, self.hours["default"])

    def method_dist(self, key: str) -> tuple[list[str], Weighted]:
        return self.methods.get(key, self.methods["default"])


@dataclass
class _Subscription:
    merchant: str
    category: str
    amount: int
    day: int
    start_idx: int
    change_idx: int | None
    new_amount: int
    cancel_idx: int | None
    method: str
    series_id: str


class UserSim:
    def __init__(self, index: int, archetype: str, cfg: GeneratorConfig, cat: Catalog) -> None:
        self.cfg, self.cat = cfg, cat
        self.p = cfg.params
        self.arch: Archetype = cfg.archetype(archetype)
        self.rng = np.random.default_rng([cfg.seed, index])
        self.index = index
        self.user_id = str(uuid.uuid5(_NAMESPACE, f"{cfg.dataset_name}:{cfg.seed}:{index}"))
        self.rows: list[dict[str, Any]] = []
        self.noise_cfg = self.p["noise"]
        self.favourites: dict[str, tuple[list[Merchant], Weighted]] = {}
        self.payday_dates: list[date] = []

        rng = self.rng
        self.user_scale = float(np.exp(rng.normal(0.0, float(self.p["user_amount_sigma"]))))
        cats = list(self.arch.category_share)
        tilt = np.exp(rng.normal(0.0, float(self.p["category_share_sigma"]), len(cats)))
        base = np.array([self.arch.category_share[c] for c in cats]) * tilt
        boosted = base * np.array([cat.boost.get(c, 1.0) for c in cats])
        self.cats = cats
        self.share_base = Weighted(base)
        self.share_boost = Weighted(boosted)
        self.share_prob = dict(zip(cats, base / base.sum(), strict=True))

        income = self.arch.income
        self.income_kind = str(income["kind"])
        if self.income_kind == "irregular":
            self.user_income = 0
            self.period_start_day = 1
        else:
            amount = float(income["amount"])
            drawn = rng.normal(amount, amount * float(income["sigma_pct"]))
            self.user_income = int(round(max(0.4 * amount, drawn) / 50_000)) * 50_000
            self.period_start_day = min(int(income["day_of_month"]), 28)

    # ---- helpers -----------------------------------------------------------------------

    def _in_range(self, d: date) -> bool:
        return self.cat.start <= d < self.cat.end

    def _method(self, key: str) -> str:
        methods, w = self.cat.method_dist(key)
        return methods[w.draw(self.rng)]

    def _when(self, category: str, day: date) -> tuple[datetime, bool]:
        rng = self.rng
        if rng.random() < float(self.p["has_time_missing_rate"]):
            return datetime.combine(day, time(12, 0)), False
        comps, weights = self.cat.hour_profile(category)
        mean, sigma = comps[weights.draw(rng)]
        hour_float = float(np.clip(rng.normal(mean, sigma), 5.0, 23.9))
        hour = int(hour_float)
        minute = int((hour_float - hour) * 60)
        return datetime.combine(day, time(hour, minute)), True

    def _favourites(self, category: str) -> tuple[list[Merchant], Weighted]:
        if category not in self.favourites:
            merchants = self.cat.by_category[category]
            cfg = self.p["favourite_merchants"]
            k = min(len(merchants), int(self.rng.integers(cfg["min"], cfg["max"] + 1)))
            w = np.array([m.weight for m in merchants], dtype=float)
            idx = self.rng.choice(len(merchants), size=k, replace=False, p=w / w.sum())
            favs = [merchants[int(i)] for i in idx]
            self.favourites[category] = (favs, Weighted([m.weight for m in favs]))
        return self.favourites[category]

    def _pick_merchant(self, category: str) -> Merchant:
        favs, w = self._favourites(category)
        if self.rng.random() < float(self.p["favourite_merchants"]["habit_prob"]):
            return favs[w.draw(self.rng)]
        merchants = self.cat.by_category[category]
        return merchants[self.cat.weighted[category].draw(self.rng)]

    def _pick_new_merchant(self, category: str) -> Merchant:
        favs, _ = self._favourites(category)
        fav_names = {m.name for m in favs}
        others = [m for m in self.cat.by_category[category] if m.name not in fav_names]
        return (
            others[int(self.rng.integers(len(others)))] if others else self._pick_merchant(category)
        )

    def _typical(self, category: str) -> float:
        return self.cat.amount_params(category)["median"] * self.arch.amount_scale * self.user_scale

    def _draw_amount(self, category: str, scale: float = 1.0) -> int:
        params = self.cat.amount_params(category)
        mu = np.log(self._typical(category) * scale)
        return round_amount(float(np.exp(self.rng.normal(mu, params["sigma"]))))

    def _emit(
        self,
        when: tuple[datetime, bool],
        merchant: str,
        abbrevs: tuple[str, ...],
        amount: int,
        ttype: str,
        method: str,
        true_category: str,
        *,
        series: str | None = None,
        anomaly: tuple[str, str] | None = None,
        ambiguous_with: tuple[str, ...] = (),
        merchant_provided: bool | None = None,
    ) -> None:
        rng = self.rng
        dt, has_time = when
        description = noise.make_description(rng, merchant, abbrevs, method, self.noise_cfg)
        provided = (
            rng.random() < float(self.noise_cfg["merchant_provided_prob"])
            if merchant_provided is None
            else merchant_provided
        )
        label = true_category
        if ambiguous_with and rng.random() < float(self.p["ambiguous_label_prob"]):
            label = noise.pick(rng, ambiguous_with)
        notes = (
            noise.pick(rng, noise.NOTES)
            if rng.random() < float(self.noise_cfg["notes_prob"])
            else None
        )
        self.rows.append(
            {
                "date": dt.strftime("%Y-%m-%d %H:%M") if has_time else dt.strftime("%Y-%m-%d"),
                "description": description,
                "amount": amount,
                "type": ttype,
                "payment_method": method,
                "merchant": merchant if provided else None,
                "category": None,
                "notes": notes,
                "transaction_id": None,
                "user_id": self.user_id,
                "archetype": self.arch.name,
                "true_category": label,
                "true_merchant": merchant,
                "is_anomaly": anomaly is not None,
                "anomaly_type": anomaly[0] if anomaly else None,
                "anomaly_severity": anomaly[1] if anomaly else None,
                "recurring_series_id": series,
                "has_time": has_time,
                "_dt": dt,
            }
        )

    def _emit_expense(
        self,
        merchant: Merchant,
        category: str,
        day_time: tuple[datetime, bool],
        amount: int,
        **kw: Any,
    ) -> None:
        self._emit(
            day_time,
            merchant.name,
            merchant.abbrevs,
            amount,
            "expense",
            self._method(category),
            category,
            ambiguous_with=merchant.ambiguous_with,
            **kw,
        )

    # ---- income ------------------------------------------------------------------------

    def _income_name(self, category: str) -> Merchant:
        merchants = self.cat.by_category[category]
        return merchants[self.cat.weighted[category].draw(self.rng)]

    def _emit_income(self, category: str, day: date, amount: int) -> None:
        m = self._income_name(category)
        when = self._when(category, day)
        self._emit(when, m.name, m.abbrevs, amount, "income", self._method("income"), category)

    def _simulate_income(self) -> None:
        rng, inc = self.rng, self.arch.income
        for first in self.cat.months:
            dim = calendar.monthrange(first.year, first.month)[1]
            if self.income_kind in ("allowance", "salary"):
                day = date(first.year, first.month, min(int(inc["day_of_month"]), dim))
                jitter = int(inc["jitter_days"])
                day += timedelta(days=int(rng.integers(-jitter, jitter + 1)))
                if self.income_kind == "salary":
                    while day.weekday() >= 5:  # weekend -> move earlier
                        day -= timedelta(days=1)
                if self._in_range(day):
                    self._emit_income(self.income_kind, day, self.user_income)
                    self.payday_dates.append(day)
            else:
                low, high = inc["payments_per_month"]
                for _ in range(int(rng.integers(low, high + 1))):
                    day = first + timedelta(days=int(rng.integers(dim)))
                    amount = (
                        int(
                            round(
                                float(
                                    np.exp(
                                        rng.normal(
                                            np.log(float(inc["median"])), float(inc["sigma"])
                                        )
                                    )
                                )
                                / 50_000
                            )
                        )
                        * 50_000
                    )
                    if amount > 0:
                        self._emit_income("freelance", day, min(amount, _MAX_AMOUNT))
                        self.payday_dates.append(day)
            for extra, prob in (("refund", 0.05), ("other_income", 0.03)):
                if rng.random() < prob:
                    day = first + timedelta(days=int(rng.integers(dim)))
                    params = self.cat.amount_params(extra)
                    amount = round_amount(
                        float(np.exp(rng.normal(np.log(params["median"]), params["sigma"])))
                    )
                    self._emit_income(extra, day, amount)

    # ---- daily discretionary expenses ----------------------------------------------------

    def _days_to_period_end(self, d: date) -> int:
        sd = self.period_start_day
        if d.day >= sd:
            nxt = _add_months(date(d.year, d.month, 1), 1)
        else:
            nxt = date(d.year, d.month, 1)
        next_start = nxt.replace(day=min(sd, calendar.monthrange(nxt.year, nxt.month)[1]))
        return (next_start - timedelta(days=1) - d).days

    def _simulate_daily(self) -> None:
        rng, arch, cat = self.rng, self.arch, self.cat
        pay_days = (
            arch.payday_days if arch.payday_days is not None else int(self.p["payday"]["days"])
        )
        pay_factor = (
            arch.payday_factor
            if arch.payday_factor is not None
            else float(self.p["payday"]["lambda_factor"])
        )
        payday_set = {pd_ + timedelta(days=i) for pd_ in self.payday_dates for i in range(pay_days)}
        lams = np.empty(len(cat.days))
        boosted_flags = []
        for i, d in enumerate(cat.days):
            lam = arch.daily_tx_lambda
            special = d.weekday() >= 5
            if d.weekday() >= 5:
                lam *= float(self.p["weekend_lambda_factor"])
            if d in cat.holidays:
                lam *= float(self.p["holiday_lambda_factor"])
                special = True
            if d in payday_set:
                lam *= pay_factor
            if (
                arch.end_of_period_days
                and self.income_kind != "irregular"
                and self._days_to_period_end(d) < arch.end_of_period_days
            ):
                lam *= arch.end_of_period_factor
            lams[i] = lam
            boosted_flags.append(special)
        counts = rng.poisson(lams)
        for i, d in enumerate(cat.days):
            n = int(counts[i])
            if n == 0:
                continue
            sampler = self.share_boost if boosted_flags[i] else self.share_base
            for _ in range(n):
                category = self.cats[sampler.draw(rng)]
                m = self._pick_merchant(category)
                self._emit_expense(
                    m, category, self._when(category, d), self._draw_amount(category)
                )

    # ---- monthly bills, transfers, subscriptions -----------------------------------------

    def _simulate_bills(self) -> None:
        rng = self.rng
        for k, bill in enumerate(self.arch.monthly_bills):
            if rng.random() >= float(bill["probability"]):
                continue
            category = str(bill["category"])
            base = self.cat.amount_params(category)["median"] * float(bill["amount_scale"])
            amount = (
                int(round(base * float(np.exp(rng.normal(0, float(bill["user_sigma"])))) / 50_000))
                * 50_000
            )
            amount = min(_MAX_AMOUNT, max(50_000, amount))
            merchant = self.cat.by_category[category][self.cat.weighted[category].draw(rng)]
            day_of_month = int(rng.integers(int(bill["day_min"]), int(bill["day_max"]) + 1))
            series = f"{self.user_id}-bill{k}"
            for first in self.cat.months:
                dim = calendar.monthrange(first.year, first.month)[1]
                day = first.replace(day=min(day_of_month, dim)) + timedelta(
                    days=int(rng.integers(0, 3))
                )
                if self._in_range(day):
                    self._emit_expense(
                        merchant, category, self._when(category, day), amount, series=series
                    )

    def _simulate_transfers(self) -> None:
        rng = self.rng
        low, high = self.arch.transfers_per_month
        merchants = self.cat.by_category["transfer"]
        params = self.cat.amount_params("transfer")
        for first in self.cat.months:
            dim = calendar.monthrange(first.year, first.month)[1]
            for _ in range(int(rng.integers(low, high + 1))):
                day = first + timedelta(days=int(rng.integers(dim)))
                m = merchants[self.cat.weighted["transfer"].draw(rng)]
                amount = (
                    int(
                        round(
                            float(np.exp(rng.normal(np.log(params["median"]), params["sigma"])))
                            / 50_000
                        )
                    )
                    * 50_000
                )
                amount = min(_MAX_AMOUNT, max(50_000, amount))
                self._emit(
                    self._when("transfer", day),
                    m.name,
                    m.abbrevs,
                    amount,
                    "transfer",
                    self._method("transfer"),
                    "transfer",
                )

    def _build_subscriptions(self) -> list[_Subscription]:
        rng, kinds = self.rng, self.cfg.subscriptions["kinds"]
        spec = self.cfg.subscriptions
        n_months = self.cfg.months
        years = n_months / 12
        chosen: list[tuple[str, dict[str, Any]]] = []  # (category, option)
        used: set[str] = set()
        for kind in self.arch.subscription_kinds:
            if rng.random() < self.arch.subscription_adoption:
                options = kinds[kind]["options"]
                option = options[int(rng.integers(len(options)))]
                chosen.append((kinds[kind]["category"], option))
                used.add(option["merchant"])
        pool = [
            (kinds[k]["category"], o)
            for k in self.arch.subscription_kinds
            for o in kinds[k]["options"]
            if o["merchant"] not in used
        ]
        for _ in range(min(self.arch.subscription_extra_services, len(pool))):
            j = int(rng.integers(len(pool)))
            chosen.append(pool.pop(j))
        subs: list[_Subscription] = []
        for n, (category, option) in enumerate(chosen):
            amounts = option["amounts"]
            amount = int(amounts[int(rng.integers(len(amounts)))])
            change_idx = cancel_idx = None
            low, high = spec["price_change_range"]
            if n_months > 1 and rng.random() < float(spec["price_change_prob_per_year"]) * years:
                change_idx = int(rng.integers(1, n_months))
            new_amount = int(round(amount * (1 + rng.uniform(low, high)) / 1000)) * 1000
            if n_months > 1 and rng.random() < float(spec["cancel_prob_per_year"]) * years:
                cancel_idx = int(rng.integers(1, n_months))
            method = self._method(category)
            subs.append(
                _Subscription(
                    merchant=str(option["merchant"]),
                    category=category,
                    amount=amount,
                    day=int(rng.integers(1, 29)),
                    start_idx=int(rng.integers(0, min(3, n_months))),
                    change_idx=change_idx,
                    new_amount=new_amount,
                    cancel_idx=cancel_idx,
                    method=method if method != "cash" else "e_wallet",
                    series_id=f"{self.user_id}-sub{n}",
                )
            )
        return subs

    def _simulate_subscriptions(self) -> None:
        rng = self.rng
        jitter = int(self.cfg.subscriptions["billing_jitter_days"])
        for sub in self._build_subscriptions():
            for idx, first in enumerate(self.cat.months):
                if idx < sub.start_idx or (sub.cancel_idx is not None and idx > sub.cancel_idx):
                    continue
                amount = (
                    sub.new_amount
                    if sub.change_idx is not None and idx >= sub.change_idx
                    else sub.amount
                )
                dim = calendar.monthrange(first.year, first.month)[1]
                day = first.replace(day=min(sub.day, dim)) + timedelta(
                    days=int(rng.integers(0, jitter + 1))
                )
                if not self._in_range(day):
                    continue
                self._emit(
                    self._when(sub.category, day),
                    sub.merchant,
                    (),
                    amount,
                    "expense",
                    sub.method,
                    sub.category,
                    series=sub.series_id,
                    merchant_provided=True,
                )

    # ---- anomalies and duplicates ---------------------------------------------------------

    def _random_time(self, day: date) -> datetime:
        return datetime.combine(
            day, time(int(self.rng.integers(7, 23)), int(self.rng.integers(60)))
        )

    def _inject_anomalies(self) -> None:
        rng, arch, cat = self.rng, self.arch, self.cat
        expense_rows = sum(1 for r in self.rows if r["type"] == "expense")
        target_rows = arch.anomaly_rate * expense_rows
        mean_rows = float(np.mean([_ROWS_PER_EVENT[t] for t in arch.anomaly_types]))
        # Events add several rows each; size the event count so the row share is ~anomaly_rate.
        for _ in range(int(rng.poisson(target_rows / mean_rows))):
            kind = arch.anomaly_types[int(rng.integers(len(arch.anomaly_types)))]
            category = self.cats[self.share_base.draw(rng)]
            day = cat.days[int(rng.integers(max(1, len(cat.days) - 8)))]
            getattr(self, f"_anomaly_{kind}")(category, day)

    def _anomaly_amount_spike(self, category: str, day: date) -> int:
        mult = float(self.rng.uniform(4.0, 15.0))
        severity = "low" if mult < 7 else "medium" if mult < 11 else "high"
        amount = round_amount(self._typical(category) * mult)
        m = self._pick_merchant(category)
        self._emit_expense(
            m, category, (self._random_time(day), True), amount, anomaly=("amount_spike", severity)
        )
        return 1

    def _anomaly_frequency_burst(self, category: str, day: date) -> int:
        rng = self.rng
        n = int(rng.integers(4, 9))
        severity = "low" if n <= 5 else "medium" if n <= 7 else "high"
        m = self._pick_merchant(category)
        start = self._random_time(day)
        for _ in range(n):
            when = (start + timedelta(minutes=int(rng.integers(0, 24 * 60 - 1))), True)
            amount = round_amount(self._typical(category) * float(rng.uniform(0.8, 1.3)))
            self._emit_expense(m, category, when, amount, anomaly=("frequency_burst", severity))
        return n

    def _anomaly_new_merchant_high_value(self, category: str, day: date) -> int:
        mult = float(self.rng.uniform(3.0, 8.0))
        severity = "low" if mult < 4.5 else "medium" if mult < 6.5 else "high"
        m = self._pick_new_merchant(category)
        amount = round_amount(max(self._typical(category) * mult, 500_000))
        self._emit_expense(
            m,
            category,
            (self._random_time(day), True),
            amount,
            anomaly=("new_merchant_high_value", severity),
        )
        return 1

    def _anomaly_category_surge(self, category: str, day: date) -> int:
        rng = self.rng
        factor = float(rng.uniform(2.5, 4.0))
        severity = "low" if factor < 3.0 else "medium" if factor < 3.5 else "high"
        per_day = self.arch.daily_tx_lambda * self.share_prob[category]
        n = max(3, int(round(per_day * 7 * (factor - 1))))
        for _ in range(n):
            d = day + timedelta(days=int(rng.integers(7)))
            if not self._in_range(d):
                d = day
            m = self._pick_merchant(category)
            self._emit_expense(
                m,
                category,
                self._when(category, d),
                self._draw_amount(category),
                anomaly=("category_surge", severity),
            )
        return n

    def _inject_duplicates(self) -> None:
        rate = float(self.p["duplicate_rate"])
        originals = [r for r in self.rows if r["type"] == "expense"]
        flags = self.rng.random(len(originals)) < rate
        self.rows.extend(dict(r) for r, dup in zip(originals, flags, strict=True) if dup)

    # ---- orchestration --------------------------------------------------------------------

    def run(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self._simulate_income()
        self._simulate_daily()
        self._simulate_bills()
        self._simulate_transfers()
        self._simulate_subscriptions()
        self._inject_anomalies()
        self._inject_duplicates()
        ordered = sorted(enumerate(self.rows), key=lambda t: (t[1]["_dt"], t[0]))
        rows = []
        for n, (_, row) in enumerate(ordered):
            row = dict(row)
            row["transaction_id"] = str(uuid.uuid5(_NAMESPACE, f"{self.user_id}:{n}"))
            del row["_dt"]
            rows.append(row)
        user = {
            "user_id": self.user_id,
            "archetype": self.arch.name,
            "income_profile": self.arch.income_profile,
            "budget_period_start_day": self.period_start_day,
            "created_at": datetime.combine(self.cat.start, time(0, 0)),
        }
        return rows, user


def simulate_chunk(
    cfg: GeneratorConfig, assignments: list[str], indices: list[int]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Simulate the users ``indices``; returns (transaction rows, user rows) in index order."""
    catalog = Catalog(cfg)
    all_rows: list[dict[str, Any]] = []
    users: list[dict[str, Any]] = []
    for i in indices:
        rows, user = UserSim(i, assignments[i], cfg, catalog).run()
        all_rows.extend(rows)
        users.append(user)
    return all_rows, users
