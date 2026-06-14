"""Small statistical helpers (pure stdlib, no numpy dependency).

A measurement "sample set" here is the set of instantaneous values within one
capture (e.g. power-monitor rows). We summarise it as the canonical
``MeasuredKpi`` shape: mean / p95 / std / ci_95 / n.
"""
from __future__ import annotations

import math
from statistics import NormalDist, fmean, pstdev

_DEFAULT_CONFIDENCE = 0.95


def _ci_z(confidence_level: float | None) -> float:
    """Two-sided z multiplier for a confidence level.

    The 0.95 default keeps the historical 1.96 constant exactly (no value
    drift); other levels use the inverse normal CDF.
    """
    if confidence_level is None or abs(confidence_level - _DEFAULT_CONFIDENCE) < 1e-9:
        return 1.96
    if not 0.0 < confidence_level < 1.0:
        raise ValueError(f"confidence_level must be in (0, 1): {confidence_level}")
    return NormalDist().inv_cdf((1.0 + confidence_level) / 2.0)


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


def measured_kpi(values: list[float], *, round_to: int = 3, confidence_level: float | None = None) -> dict:
    """Summarise a sample set into a MeasuredKpi-shaped dict.

    std is the population standard deviation over the sample set; ci_95 is the
    normal-approximation confidence interval of the mean (only when n > 1).
    ``confidence_level`` drives the interval width: None/0.95 keep the standard
    95% interval; any other level (e.g. 0.90, 0.99) is honoured and recorded in
    ``ci_level`` so the interval's meaning stays explicit.
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
        half = _ci_z(confidence_level) * std / math.sqrt(n)
        out["ci_95"] = [round(mean - half, round_to), round(mean + half, round_to)]
        if confidence_level is not None and abs(confidence_level - _DEFAULT_CONFIDENCE) > 1e-9:
            out["ci_level"] = confidence_level
    return out
