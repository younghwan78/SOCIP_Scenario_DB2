"""Small statistical helpers (pure stdlib, no numpy dependency).

A measurement "sample set" here is the set of instantaneous values within one
capture (e.g. power-monitor rows). We summarise it as the canonical
``MeasuredKpi`` shape: mean / p95 / std / ci_95 / n.
"""
from __future__ import annotations

import math
from statistics import fmean, pstdev


def percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100]). Matches numpy's default."""
    if not values:
        raise ValueError("percentile of empty sequence")
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    frac = rank - low
    return float(ordered[low] * (1.0 - frac) + ordered[high] * frac)


def measured_kpi(values: list[float], *, round_to: int = 3) -> dict:
    """Summarise a sample set into a MeasuredKpi-shaped dict.

    std is the population standard deviation over the capture; ci_95 is the
    normal-approximation confidence interval of the mean (only when n > 1).
    """
    if not values:
        raise ValueError("measured_kpi of empty sequence")
    n = len(values)
    mean = fmean(values)
    std = pstdev(values) if n > 1 else 0.0
    out: dict = {
        "mean": round(mean, round_to),
        "p95": round(percentile(values, 95.0), round_to),
        "std": round(std, round_to),
        "n": n,
    }
    if n > 1 and std > 0.0:
        half = 1.96 * std / math.sqrt(n)
        out["ci_95"] = [round(mean - half, round_to), round(mean + half, round_to)]
    return out
