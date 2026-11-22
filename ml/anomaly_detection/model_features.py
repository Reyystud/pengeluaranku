"""User-relative anomaly features of PRD 11.2.2, computed for a whole user in one pass.

Every feature of a transaction uses only rows with ``occurred_at`` strictly before it (PRD 11.1
rule 2); ``tests/test_anomaly_model.py`` proves it by injecting future rows. The history window is
180 days (``config/anomaly.yaml``). A category with fewer than ``cold_start.min_category_history``
prior transactions uses the global category prior for the median and MAD (7.6.4).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ml.anomaly_detection.config import AnomalyConfig

FEATURE_VERSION = "anomaly-model-features-1"
FEATURES = (
    "z_cat",
    "z_merchant",
    "pct_rank_cat",
    "ratio_to_cat_median",
    "merchant_seen",
    "merchant_count_180d",
    "cat_count_24h",
    "cat_count_7d",
    "cat_rate_56d",
    "cat_spend_7d_ratio",
    "hour_sin",
    "hour_cos",
    "hour_known",
    "dow_sin",
    "dow_cos",
    "days_since_income",
    "history_n_cat",
)
DAY = np.timedelta64(1, "D")
NO_INCOME_DAYS = 400.0  # days_since_income when the user has no earlier income row
MERCHANT_MIN_OBS = 3  # z_merchant needs at least this many prior expenses at the merchant


def _mad(values: np.ndarray, median: float) -> float:
    return float(np.median(np.abs(values - median)))


def user_features(
    rows: pd.DataFrame,
    cfg: AnomalyConfig,
    priors: dict[str, tuple[float, float]],
    min_category_history: int,
) -> pd.DataFrame:
    """Features of every expense row of ONE user. ``rows`` needs occurred_at (sorted), type,
    amount_f, category, merchant_key, has_time. Returns FEATURES plus ``base_typ`` (exp of the
    category median of log1p, used by the baseline gate) indexed like ``rows``."""
    times = rows["occurred_at"].to_numpy(dtype="datetime64[ns]")
    amount = rows["amount_f"].to_numpy(dtype=float)
    is_expense = (rows["type"] == "expense").to_numpy()
    cats = rows["category"].to_numpy()
    merchants = rows["merchant_key"].to_numpy()
    has_time = rows["has_time"].to_numpy(dtype=bool)
    log_amount = np.log1p(amount)
    window = np.timedelta64(cfg.history_days, "D")

    def group(mask: np.ndarray, keys: np.ndarray) -> dict[str, np.ndarray]:
        out: dict[str, list[int]] = {}
        for i in np.flatnonzero(mask):
            out.setdefault(str(keys[i]), []).append(int(i))
        return {k: np.asarray(v) for k, v in out.items()}

    by_cat = group(is_expense, cats)
    by_merchant_all = group(np.ones(len(rows), dtype=bool), merchants)
    cat_times = {k: times[v] for k, v in by_cat.items()}
    cat_cum = {k: np.concatenate([[0.0], np.cumsum(amount[v])]) for k, v in by_cat.items()}
    merchant_times = {k: times[v] for k, v in by_merchant_all.items()}
    income_times = times[(rows["type"] == "income").to_numpy()]

    positions = {i: (k, p) for k, v in by_cat.items() for p, i in enumerate(v)}
    out = np.full((len(rows), len(FEATURES) + 1), np.nan)
    col = {name: j for j, name in enumerate((*FEATURES, "base_typ"))}
    for i in np.flatnonzero(is_expense):
        t = times[i]
        c, _ = positions[int(i)]
        idx, ct, cum = by_cat[c], cat_times[c], cat_cum[c]
        hi = int(np.searchsorted(ct, t, side="left"))
        lo = int(np.searchsorted(ct, t - window, side="left"))
        hist_idx = idx[lo:hi]
        hist = log_amount[hist_idx]
        n_cat = len(hist)
        prior = priors.get(c)
        x = log_amount[i]
        if n_cat >= min_category_history:
            m = float(np.median(hist))
            mad = _mad(hist, m)
            typical = float(np.median(amount[hist_idx]))
            rank = float((hist <= x).mean())
        elif prior is not None:
            m, mad = prior
            typical = math.expm1(m)
            rank = 0.5
        else:
            m, mad, typical, rank = x, 1.0, float(amount[i]), 0.5
        z = cfg.z_scale * (x - m) / max(mad, cfg.mad_floor)

        mk = str(merchants[i])
        mt = merchant_times[mk]
        seen_hi = int(np.searchsorted(mt, t, side="left"))
        seen_lo = int(np.searchsorted(mt, t - window, side="left"))
        m_idx = by_merchant_all[mk][seen_lo:seen_hi]
        m_exp = m_idx[is_expense[m_idx]]
        if len(m_exp) >= MERCHANT_MIN_OBS:
            ml = log_amount[m_exp]
            mm = float(np.median(ml))
            z_merchant = cfg.z_scale * (x - mm) / max(_mad(ml, mm), cfg.mad_floor)
        else:
            z_merchant = 0.0

        lo24 = int(np.searchsorted(ct, t - DAY, side="right"))
        lo7 = int(np.searchsorted(ct, t - 7 * DAY, side="right"))
        lo56 = int(np.searchsorted(ct, t - cfg.burst_rate_days * DAY, side="left"))
        spend7 = amount[i] + (cum[hi] - cum[lo7] if hi > lo7 else 0.0)
        weekly = []
        for k in range(1, 9):
            a = int(np.searchsorted(ct, t - 7 * (k + 1) * DAY, side="right"))
            b = int(np.searchsorted(ct, t - 7 * k * DAY, side="right"))
            weekly.append(cum[min(b, hi)] - cum[min(a, hi)] if b > a else 0.0)
        med_week = float(np.median(weekly))
        ts = pd.Timestamp(t)
        hour = ts.hour + ts.minute / 60
        n_income = int(np.searchsorted(income_times, t, side="left"))
        since_income = (t - income_times[n_income - 1]) / DAY if n_income else NO_INCOME_DAYS
        known = bool(has_time[i])
        row = {
            "z_cat": z,
            "z_merchant": z_merchant,
            "pct_rank_cat": rank,
            "ratio_to_cat_median": float(amount[i]) / max(typical, 1.0),
            "merchant_seen": float(seen_hi > 0),
            "merchant_count_180d": float(len(m_idx)),
            "cat_count_24h": float(hi - lo24 + 1),
            "cat_count_7d": float(hi - lo7 + 1),
            "cat_rate_56d": (hi - lo56) / cfg.burst_rate_days,
            "cat_spend_7d_ratio": spend7 / med_week if med_week > 0 else 0.0,
            "hour_sin": math.sin(2 * math.pi * hour / 24) if known else 0.0,
            "hour_cos": math.cos(2 * math.pi * hour / 24) if known else 0.0,
            "hour_known": float(known),
            "dow_sin": math.sin(2 * math.pi * ts.dayofweek / 7),
            "dow_cos": math.cos(2 * math.pi * ts.dayofweek / 7),
            "days_since_income": float(since_income),
            "history_n_cat": float(n_cat),
            "base_typ": math.exp(m),
        }
        for name, value in row.items():
            out[i, col[name]] = value
    frame = pd.DataFrame(out, index=rows.index, columns=[*FEATURES, "base_typ"])
    return frame[is_expense]
