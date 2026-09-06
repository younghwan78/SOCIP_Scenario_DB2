"""Small statistical helpers (pure stdlib, no numpy dependency).

A measurement "sample set" here is the set of repeated-run values within one
capture (e.g. per-run power means). We summarise it as the canonical
``MeasuredKpi`` shape: mean / p95 / std / ci_95 / n.

Run counts are small (typically n=3), so the confidence interval uses the
sample standard deviation and a Student-t multiplier with n-1 degrees of
freedom. The earlier population-sigma + z=1.96 form understated a 3-run CI by
roughly 2.7x.
"""
from __future__ import annotations

import math
from statistics import fmean, stdev

_DEFAULT_CONFIDENCE = 0.95


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta function."""
    max_iter = 200
    eps = 3e-12
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _t_cdf(t: float, dof: int) -> float:
    """Student-t cumulative distribution function."""
    if t == 0.0:
        return 0.5
    x = dof / (dof + t * t)
    tail = 0.5 * _betai(dof / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_multiplier(confidence_level: float, dof: int) -> float:
    """Two-sided Student-t quantile for a confidence level and dof (bisection)."""
    if not 0.0 < confidence_level < 1.0:
        raise ValueError(f"confidence_level must be in (0, 1): {confidence_level}")
    if dof < 1:
        raise ValueError(f"dof must be >= 1: {dof}")
    target = (1.0 + confidence_level) / 2.0
    lo, hi = 0.0, 1e6
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _t_cdf(mid, dof) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-9 * max(1.0, hi):
            break
    return (lo + hi) / 2.0


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

    std is the sample standard deviation (n-1 denominator); ci_95 is the
    Student-t confidence interval of the mean (only when n > 1), which is the
    correct small-n treatment for repeated-run measurements.
    ``confidence_level`` drives the interval width: None keeps the standard
    95% interval; any other level (e.g. 0.90, 0.99) is honoured and recorded
    in ``ci_level`` so the interval's meaning stays explicit.
    """
    if not values:
        raise ValueError("measured_kpi of empty sequence")
    n = len(values)
    mean = fmean(values)
    std = stdev(values) if n > 1 else 0.0
    out: dict = {
        "mean": round(mean, round_to),
        "p95": round(percentile(values, 95.0), round_to),
        "std": round(std, round_to),
        "n": n,
    }
    if n > 1 and std > 0.0:
        level = _DEFAULT_CONFIDENCE if confidence_level is None else confidence_level
        half = t_multiplier(level, n - 1) * std / math.sqrt(n)
        out["ci_95"] = [round(mean - half, round_to), round(mean + half, round_to)]
        if confidence_level is not None and abs(confidence_level - _DEFAULT_CONFIDENCE) > 1e-9:
            out["ci_level"] = confidence_level
    return out
