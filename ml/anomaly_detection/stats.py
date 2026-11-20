"""Small, exact statistics helpers for the baseline detector (PRD 7.6.2)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def median(values: Sequence[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n == 0:
        raise ValueError("median of an empty sequence")
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def mad(values: Sequence[float]) -> float:
    """Median absolute deviation around the median."""
    m = median(values)
    return median([abs(v - m) for v in values])


def modified_z(x: float, m: float, mad_value: float, floor: float, scale: float) -> float:
    """Iglewicz-Hoaglin: ``scale * (x - m) / max(MAD, floor)``."""
    return scale * (x - m) / max(mad_value, floor)


def clip01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def poisson_sf(k: int, lam: float, terms: int = 200) -> float:
    """``P(X >= k)`` for ``X ~ Poisson(lam)``: the upper tail summed directly.

    Summing the tail itself (not ``1 - P(X < k)``) keeps full precision for the tiny probabilities
    the burst rule cares about (1e-3 and below).
    """
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    total = sum(
        math.exp(-lam + i * math.log(lam) - math.lgamma(i + 1)) for i in range(k, k + terms)
    )
    return min(total, 1.0)


def percentile(values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile (the same definition as PostgreSQL ``percentile_cont``)."""
    s = sorted(values)
    if not s:
        raise ValueError("percentile of an empty sequence")
    pos = q * (len(s) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def percent_rank(value: float, values: Sequence[float]) -> float:
    """Share of ``values`` that are strictly lower, 0..100."""
    if not values:
        return 0.0
    return 100.0 * sum(1 for v in values if v < value) / len(values)
