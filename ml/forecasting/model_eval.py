"""ETS and LightGBM quantile vs the run-rate / seasonal-naive baselines (PRD 7.7.3, 9.4).

    uv run python -m ml.forecasting.model_eval [--users N] [--no-mlflow] [--out report.json]

Rolling origin (10.4): the origins are day 5/10/15/20 of each of the last four periods of a
deterministic user sample (``data_splits/.../forecast_periods.csv``). The target is the period
total of **non-recurring** expenses (7.7.1). Everything a forecast uses lies at or before its
origin day. The global LightGBM is trained once, only on origins of periods that END before the
user's first evaluated period, so no evaluated period or origin is ever seen.

Deviation from 11.2.3 (recorded in DECISIONS): the LightGBM predicts the *remaining total* to the
end of the period directly (one row per origin, ``days_remaining`` plays the role of
``days_ahead``) instead of one row per future day. Summing daily quantiles does not give the
quantile of the sum, and the product only needs the total. Level features are divided by the
user's 56-day mean so one model fits users whose spending differs by orders of magnitude.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml.config import _load_yaml, load_holidays
from ml.evaluation.loading import load_transactions, sample_users
from ml.forecasting.baseline import Forecast, forecast
from ml.forecasting.config import load_forecast_config

ROOT = Path(__file__).resolve().parents[2]
FEATURE_VERSION = "forecast-model-features-1"
FEATURES = (
    "days_remaining",
    "days_elapsed",
    "dow",
    "dom",
    "weekends_remaining",
    "holidays_remaining",
    "days_since_income",
    "rel_mean_7",
    "rel_mean_28",
    "rel_cv_28",
    "rel_ptd",
    "rel_seasonal_remaining",
    "rel_runrate_remaining",
)
NO_INCOME_DAYS = 400.0


class UserSeries:
    """Daily non-recurring expense of one user, zero-filled from the first transaction."""

    def __init__(self, rows: pd.DataFrame, last_day: date) -> None:
        self.first = rows["occurred_at"].min().date()
        n = (last_day - self.first).days + 1
        self.days = [self.first + timedelta(days=i) for i in range(n)]
        self.y = np.zeros(n)
        spend = rows[(rows["type"] == "expense") & rows["recurring_series_id"].isna()]
        idx = (
            spend["occurred_at"].dt.normalize().dt.date.map(lambda d: (d - self.first).days)
        ).to_numpy()
        np.add.at(self.y, idx, spend["amount_f"].to_numpy())
        self.income = np.zeros(n, dtype=bool)
        inc = rows[rows["type"] == "income"]
        self.income[
            (
                inc["occurred_at"].dt.normalize().dt.date.map(lambda d: (d - self.first).days)
            ).to_numpy()
        ] = True
        self.weekday = np.array([d.weekday() for d in self.days])

    def idx(self, d: date) -> int:
        return int((d - self.first).days)


def seasonal_remaining(s: UserSeries, i: int, h: int, weeks: int) -> float:
    """Sum over the remaining days of the mean of the last ``weeks`` same weekdays up to ``i``."""
    total = 0.0
    for k in range(1, h + 1):
        first_m = -(-k // 7)  # ceil(k / 7): the first lag in whole weeks that is <= the origin
        vals = [s.y[i + k - 7 * m] for m in range(first_m, first_m + weeks) if i + k - 7 * m >= 0]
        total += sum(vals) / len(vals) if vals else 0.0
    return total


def origin_row(
    s: UserSeries, i: int, ps: int, pe: int, holidays: set[date], weeks: int
) -> tuple[dict[str, float], float, float, float]:
    """(features, scale, spent_to_date, runrate) for origin index ``i`` of the period [ps, pe]."""
    h = pe - i
    ps = max(ps, 0)
    elapsed = i - ps + 1
    ptd = float(s.y[ps : i + 1].sum())

    def mean(k: int) -> float:
        return float(s.y[max(i - k + 1, 0) : i + 1].mean())

    rm56, rm7, rm28 = mean(56), mean(7), mean(28)
    sd28 = float(s.y[max(i - 27, 0) : i + 1].std())
    scale = max(rm56 * h, 1.0)
    base = rm56 if rm56 > 0 else 1.0
    seasonal = seasonal_remaining(s, i, h, weeks)
    runrate = ptd / elapsed * h
    future = [s.days[i] + timedelta(days=k) for k in range(1, h + 1)]
    inc = np.flatnonzero(s.income[: i + 1])
    row = {
        "days_remaining": float(h),
        "days_elapsed": float(elapsed),
        "dow": float(s.weekday[i]),
        "dom": float(s.days[i].day),
        "weekends_remaining": float(sum(d.weekday() >= 5 for d in future)),
        "holidays_remaining": float(sum(d in holidays for d in future)),
        "days_since_income": float(i - inc[-1]) if len(inc) else NO_INCOME_DAYS,
        "rel_mean_7": rm7 / base,
        "rel_mean_28": rm28 / base,
        "rel_cv_28": sd28 / base,
        "rel_ptd": ptd / (base * elapsed),
        "rel_seasonal_remaining": seasonal / scale,
        "rel_runrate_remaining": runrate / scale,
    }
    return row, scale, ptd, runrate


def mase_scale(s: UserSeries, i: int, h: int, lag: int, window: int) -> float:
    """In-sample MAE of the seasonal-naive forecast of an ``h``-day total (PRD 9.4, m = 7)."""
    y = s.y[: i + 1]
    if len(y) < h + lag + 1:
        return float("nan")
    cum = np.concatenate([[0.0], np.cumsum(y)])
    start = max(len(y) - h - window, lag)
    t = np.arange(start, len(y) - h + 1)  # S_t = sum of y[t .. t+h-1]
    sums = cum[t + h] - cum[t]
    naive = cum[t + h - lag] - cum[t - lag]
    return float(np.mean(np.abs(sums - naive)))


def period_table(periods: pd.DataFrame, users: list[str]) -> dict[str, list[tuple[date, date]]]:
    p = periods[periods["user_id"].isin(users)].sort_values(["user_id", "period_start"])
    return {
        str(u): [
            (date.fromisoformat(a), date.fromisoformat(b))
            for a, b in zip(g["period_start"], g["period_end"], strict=True)
        ]
        for u, g in p.groupby("user_id")
    }


def months_back(day: date, k: int) -> date:
    """The same day of the month ``k`` months earlier (period start days are 1 to 28)."""
    month = day.month - k
    year = day.year + (month - 1) // 12
    return date(year, (month - 1) % 12 + 1, day.day)


def training_rows(
    s: UserSeries, first_eval_start: date, holidays: set[date], weeks: int, min_history: int
) -> list[tuple[dict[str, float], float]]:
    """(features, target ratio) for every origin of the periods that end before the first eval."""
    rows = []
    start = first_eval_start
    k = 1
    while True:
        ps_date = months_back(first_eval_start, k)
        pe_date = start - timedelta(days=1)
        if ps_date < s.first or (pe_date - s.first).days < min_history:
            break
        ps, pe = s.idx(ps_date), s.idx(pe_date)
        for i in range(max(ps, min_history - 1), pe):
            feats, scale, _, _ = origin_row(s, i, ps, pe, holidays, weeks)
            rows.append((feats, float(s.y[i + 1 : pe + 1].sum()) / scale))
        start = ps_date
        k += 1
    return rows


def fit_quantiles(
    x: pd.DataFrame, y: np.ndarray, cfg: dict[str, Any], seed: int
) -> dict[float, lgb.LGBMRegressor]:
    params = {k: v for k, v in cfg["lightgbm"].items() if k != "quantiles"}
    return {
        float(q): lgb.LGBMRegressor(
            objective="quantile", alpha=float(q), random_state=seed, verbose=-1, **params
        ).fit(x, y)
        for q in cfg["lightgbm"]["quantiles"]
    }


def ets_remaining(
    s: UserSeries, i: int, h: int, window: int, periods: int
) -> tuple[float, float] | None:
    """(point remaining total, residual std) of a per-user additive ETS, or None if it fails."""
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    y = s.y[max(i - window + 1, 0) : i + 1]
    if len(y) < 2 * periods or float(y.std()) == 0.0:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ETSModel(
                y,
                error="add",
                trend=None,
                seasonal="add",
                seasonal_periods=periods,
                initialization_method="estimated",
            ).fit(disp=False)
            pred = np.clip(np.asarray(fit.forecast(h)), 0.0, None)
            return float(pred.sum()), float(np.std(fit.resid))
    except Exception:  # noqa: BLE001 - a failed fit falls back to the baseline; counted in the report
        return None


def wape(err: np.ndarray, actual: np.ndarray) -> float:
    return float(np.abs(err).sum() / actual.sum()) if actual.sum() > 0 else float("nan")


def summarize(df: pd.DataFrame, models: list[str]) -> dict[str, Any]:
    def block(d: pd.DataFrame) -> dict[str, Any]:
        out: dict[str, Any] = {"n": int(len(d))}
        for m in models:
            err = (d[f"{m}_p50"] - d["actual"]).to_numpy()
            out[m] = {
                "wape": wape(err, d["actual"].to_numpy()),
                "mae": float(np.abs(err).mean()),
                "mase": float(np.nanmean(np.abs(d[f"{m}_p50"] - d["actual"]) / d["mase_scale"])),
                "coverage": float(
                    ((d["actual"] >= d[f"{m}_low"]) & (d["actual"] <= d[f"{m}_high"])).mean()
                )
                if f"{m}_low" in d
                else None,
            }
        return out

    return {
        "overall": block(df),
        "by_origin_day": {int(str(k)): block(g) for k, g in df.groupby("origin_day")},
        "by_archetype": {str(k): block(g) for k, g in df.groupby("archetype")},
    }


def ship_decision(summary: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """PRD 9.1: WAPE below run-rate at every origin day AND coverage inside the band.

    ``beats_seasonal_naive`` is stricter than the PRD rule and is reported next to it: from 60 days
    of history the product's baseline is the seasonal naive forecast (7.7.2), not the run-rate.
    """
    lo, hi = cfg["ship_rule"]["coverage_min"], cfg["ship_rule"]["coverage_max"]
    out = []
    for m in ("ets", "lightgbm_quantile"):
        days = summary["by_origin_day"]
        vs_run_rate = {d: g[m]["wape"] < g["run_rate"]["wape"] for d, g in days.items()}
        vs_seasonal = {d: g[m]["wape"] < g["baseline"]["wape"] for d, g in days.items()}
        cov = summary["overall"][m]["coverage"]
        in_band = bool(lo <= cov <= hi)
        out.append(
            {
                "model": m,
                "wape_below_run_rate_by_origin_day": vs_run_rate,
                "wape_below_seasonal_naive_by_origin_day": vs_seasonal,
                "coverage": cov,
                "coverage_in_band": in_band,
                "ships": bool(all(vs_run_rate.values()) and in_band),
                "beats_seasonal_naive": bool(all(vs_seasonal.values())),
            }
        )
    return out


def run(cfg: dict[str, Any]) -> dict[str, Any]:
    t0 = time.time()
    fc = load_forecast_config()
    data_dir = ROOT / cfg["dataset"]["data_dir"]
    periods = pd.read_csv(ROOT / cfg["dataset"]["periods"], dtype=str)
    users = sample_users(
        sorted(periods["user_id"].unique().tolist()),
        int(cfg["sample"]["users"]),
        str(cfg["sample"]["salt"]),
    )
    tx = load_transactions(data_dir, users)
    last_day = tx["occurred_at"].max().date()
    plan = period_table(periods, users)
    years, hols = load_holidays()
    holidays = {h.day for h in hols if h.kind == "national"}
    weeks, min_history = fc.seasonal_weeks, int(cfg["min_history_days"])
    series = {u: UserSeries(g, last_day) for u, g in tx.groupby("user_id")}
    archetype = tx.groupby("user_id")["archetype"].first().to_dict()

    train: list[tuple[dict[str, float], float]] = []
    for u in users:
        train += training_rows(series[u], plan[u][0][0], holidays, weeks, min_history)
    x_train = pd.DataFrame([r[0] for r in train])[list(FEATURES)]
    models = fit_quantiles(x_train, np.array([r[1] for r in train]), cfg, int(cfg["seed"]))
    fit_seconds = time.time() - t0

    rows: list[dict[str, Any]] = []
    ets_failed = 0
    z = fc.z
    for u in users:
        s = series[u]
        for ps_date, pe_date in plan[u]:
            ps, pe = s.idx(ps_date), s.idx(pe_date)
            actual = float(s.y[max(ps, 0) : pe + 1].sum())
            for d in cfg["origin_days"]:
                i = ps + d - 1
                if i >= pe:
                    continue
                h = pe - i
                feats, scale, ptd, runrate = origin_row(s, i, ps, pe, holidays, weeks)
                history = list(zip(s.days[: i + 1], s.y[: i + 1].tolist(), strict=True))
                base = forecast(
                    spent_to_date=ptd,
                    today=s.days[i],
                    period_start=ps_date,
                    period_end=pe_date,
                    history=history,
                    history_days=i + 1,
                    transactions=0,
                    require_transactions=False,
                    cfg=fc,
                )
                assert isinstance(base, Forecast)
                row: dict[str, Any] = {
                    "user_id": u,
                    "archetype": archetype[u],
                    "period_start": str(ps_date),
                    "origin_day": d,
                    "actual": actual,
                    "mase_scale": mase_scale(
                        s,
                        i,
                        h,
                        int(cfg["mase"]["seasonal_lag_days"]),
                        int(cfg["mase"]["window_days"]),
                    ),
                    "baseline_p50": base.predicted_total,
                    "baseline_low": base.interval_low,
                    "baseline_high": base.interval_high,
                    "run_rate_p50": ptd + runrate,
                    "run_rate_low": base.interval_low - base.predicted_total + ptd + runrate,
                    "run_rate_high": base.interval_high - base.predicted_total + ptd + runrate,
                }
                e = ets_remaining(
                    s, i, h, int(cfg["ets"]["window_days"]), int(cfg["ets"]["seasonal_periods"])
                )
                if e is None:
                    ets_failed += 1
                    row.update(
                        ets_p50=base.predicted_total,
                        ets_low=base.interval_low,
                        ets_high=base.interval_high,
                    )
                else:
                    rem, sigma = e
                    width = z * sigma * float(np.sqrt(h))
                    row.update(
                        ets_p50=ptd + rem,
                        ets_low=ptd + max(rem - width, 0.0),
                        ets_high=ptd + rem + width,
                    )
                xr = pd.DataFrame([feats])[list(FEATURES)]
                q = sorted(float(models[k].predict(xr)[0]) * scale for k in sorted(models))
                row.update(
                    lightgbm_quantile_p50=ptd + max(q[1], 0.0),
                    lightgbm_quantile_low=ptd + max(q[0], 0.0),
                    lightgbm_quantile_high=ptd + max(q[2], 0.0),
                )
                rows.append(row)
    df = pd.DataFrame(rows)
    summary = summarize(df, ["baseline", "run_rate", "ets", "lightgbm_quantile"])
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    ).stdout.strip()
    return {
        "config_version": cfg["version"],
        "feature_version": FEATURE_VERSION,
        "baseline_version": fc.version,
        "dataset_version": cfg["dataset"]["dataset_version"],
        "users_sampled": len(users),
        "evaluated_origins": int(len(df)),
        "training_rows": len(train),
        "ets_fallbacks": ets_failed,
        "holiday_years": list(years),
        "git_commit": commit,
        "fit_seconds": round(fit_seconds, 1),
        "total_seconds": round(time.time() - t0, 1),
        "summary": summary,
        "ship": ship_decision(summary, cfg),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=None)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    cfg = _load_yaml("train/forecast.yaml")
    if args.users:
        cfg["sample"]["users"] = args.users
    report = run(cfg)
    if not args.no_mlflow:
        from ml.tracking import log_run

        flat: dict[str, float] = {}
        for m in ("baseline", "run_rate", "ets", "lightgbm_quantile"):
            o = report["summary"]["overall"][m]
            flat |= {f"{m}_wape": o["wape"], f"{m}_mae": o["mae"], f"{m}_mase": o["mase"]}
            if o["coverage"] is not None:
                flat[f"{m}_coverage"] = o["coverage"]
        report["mlflow_run_id"] = log_run(
            "expense-forecaster",
            f"{cfg['version']}-{report['git_commit']}",
            {
                "version": cfg["version"],
                "seed": cfg["seed"],
                "users": report["users_sampled"],
                "dataset_version": report["dataset_version"],
                "feature_version": FEATURE_VERSION,
                "git_commit": report["git_commit"],
            },
            flat,
            {"evaluation/report.json": report},
        )
    text = json.dumps(report, indent=2, default=float)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
