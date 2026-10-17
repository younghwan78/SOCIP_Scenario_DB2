"""Prediction ↔ measurement calibration on the ScenarioDB power split.

Measured rails are grouped into the same four buckets the predictions use:

- ``cpu``  CPU clusters (SW tasks)
- ``ip``   multimedia/SoC IP core rails (CAM, INT, ...)
- ``bw``   memory traffic: MIF + DRAM rails (the model books DMA power here)
- ``other`` rails the scenario power model does not cover (GPU, SRAM, ICPU, ...)

A project's ``sim_config_profile.rail_domain_map`` wins over the name rules.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

CATEGORIES = ("cpu", "ip", "bw", "other")
_DOMAIN_TO_CATEGORY = {"CPU": "cpu", "MIF": "bw", "MEM": "bw", "DRAM": "bw",
                       **dict.fromkeys(("GPU", "G3D", "SRAM", "ICPU", "NPU", "DNC", "AUD", "MODEM", "CP"), "other")}
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("other", re.compile(r"G3D|GPU|SRAM|ICPU|NPU|DNC|AUD|MODEM|_CP_", re.I)),
    ("cpu", re.compile(r"CPUCL|_DSU|VDD_CPU", re.I)),
    ("bw", re.compile(r"VDDMIF|_MIF|VDD2H|VDD2L|VDDQ|VDD1_MEM|_MEM_|DRAM", re.I)),
    ("ip", re.compile(r"CAM|_INT_|_INT$|VDD_INT|MFC|DPU|DISP|ISP|MM", re.I)),
)


def rail_category(rail: str, rail_domain_map: dict[str, str] | None = None, domain_hint: str | None = None) -> str:
    domain = (rail_domain_map or {}).get(rail) or domain_hint
    if domain:
        return _DOMAIN_TO_CATEGORY.get(str(domain).upper(), "ip")
    for category, pattern in _RULES:
        if pattern.search(rail):
            return category
    return "other"


def measured_split(vdd_power: dict[str, Any] | None, rail_domain_map: dict[str, str] | None = None) -> dict[str, Any]:
    rails: list[dict[str, Any]] = []
    cats = {c: 0.0 for c in CATEGORIES}
    var = {c: 0.0 for c in CATEGORIES}
    for rail, row in sorted((vdd_power or {}).items()):
        if not isinstance(row, dict) or row.get("power_mw") is None:
            continue
        cat = rail_category(rail, rail_domain_map, row.get("domain"))
        p = float(row["power_mw"])
        s = float(row.get("std_mw") or 0.0)
        cats[cat] += p
        var[cat] += s * s
        rails.append({"rail": rail, "category": cat, "power_mw": round(p, 3), "std_mw": round(s, 3),
                      "voltage_v": row.get("voltage_v"), "current_ma": row.get("current_ma"),
                      "domain": row.get("domain") or (rail_domain_map or {}).get(rail)})
    rails.sort(key=lambda r: (CATEGORIES.index(str(r["category"])), -float(r["power_mw"] or 0.0)))
    return {
        "categories": {c: round(v, 3) for c, v in cats.items()},
        "category_std": {c: round(v ** 0.5, 3) for c, v in var.items()},
        "rail_total_mw": round(sum(cats.values()), 3),
        "rails": rails,
    }


def pct(pred: float | None, meas: float | None) -> float | None:
    if pred is None or meas is None or meas == 0:
        return None
    return round(100.0 * (pred - meas) / meas, 2)


def compare_split(pred: dict[str, float] | None, meas: dict[str, float]) -> list[dict[str, Any]]:
    """Per-category rows; ``other`` has no prediction (unmodeled).

    A predicted 0 mW means the source did not model that category (e.g. a sim
    without CPU power) — it is reported as unmodeled, not as a -100 % error.
    """
    rows = []
    for c in CATEGORIES:
        p = None if pred is None or c == "other" else pred.get(c)
        if p is not None and p <= 0:
            p = None
        m = meas.get(c)
        rows.append({"category": c, "prediction_mw": None if p is None else round(p, 3), "measurement_mw": m,
                     "delta_mw": None if p is None or m is None else round(p - m, 3), "delta_pct": pct(p, m)})
    return rows


# Total within this band while a modelled category is off by more than OFFSET_CATEGORY_PCT:
# the total matches by compensation between categories, not because the model is right.
OFFSET_TOTAL_PCT = 10.0
OFFSET_CATEGORY_PCT = 25.0


def category_fit(rows: list[dict[str, Any]] | None, total_delta_pct: float | None) -> dict[str, Any]:
    """Worst modelled-category error of a ``compare_split`` result and whether the total hides it."""
    worst: dict[str, Any] | None = None
    for r in rows or []:
        d = r.get("delta_pct")
        if d is None:
            continue
        if worst is None or abs(d) > abs(worst["delta_pct"]):
            worst = {"category": r["category"], "delta_pct": d}
    offsetting = (
        worst is not None and total_delta_pct is not None
        and abs(total_delta_pct) <= OFFSET_TOTAL_PCT and abs(worst["delta_pct"]) > OFFSET_CATEGORY_PCT
    )
    return {"worst_category": worst["category"] if worst else None,
            "worst_delta_pct": worst["delta_pct"] if worst else None,
            "offsetting": bool(offsetting)}


# ---------------------------------------------------------------------------
# Model-level bias across many variants (calibration summary, report "모델 신뢰도")
# ---------------------------------------------------------------------------
FIT_OK_PCT = 10.0
FIT_WARN_PCT = 25.0
# A category whose errors share one sign in this share of variants, with |median| beyond
# FIT_WARN_PCT, is a model-wide error (a coefficient or the model form), not a scenario one.
MODEL_COMMON_SAME_SIGN = 0.8

BIAS_VERDICT_LABEL = {
    "ok": "일치",
    "model_common": "모델 공통 오차",
    "bias": "공통 경향",
    "scenario": "scenario별 오차",
    "insufficient": "비교 부족",
}


def _quantile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bias_stats(values: Sequence[float | None], *, min_n: int = 3) -> dict[str, Any]:
    """Distribution of signed Δ% (prediction − measurement) over variants for one category.

    ``verdict``: ``ok`` (≥ 80 % of variants within ±10 %), ``model_common`` (one sign in
    ≥ 80 % and |median| > 25 %), ``bias`` (one sign in ≥ 80 %, |median| ≤ 25 %),
    ``scenario`` (errors spread across signs) or ``insufficient`` (fewer than ``min_n``).
    """
    vals = sorted(float(v) for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return {"n": 0, "median": None, "p25": None, "p75": None, "min": None, "max": None,
                "within10": 0, "within25": 0, "same_sign_pct": None, "sign": 0, "verdict": "insufficient"}
    med = _quantile(vals, 0.5)
    pos = sum(1 for v in vals if v > 0)
    neg = sum(1 for v in vals if v < 0)
    same = max(pos, neg) / n
    within10 = sum(1 for v in vals if abs(v) <= FIT_OK_PCT)
    if n < min_n:
        verdict = "insufficient"
    elif within10 / n >= MODEL_COMMON_SAME_SIGN:
        verdict = "ok"
    elif same >= MODEL_COMMON_SAME_SIGN and abs(med) > FIT_WARN_PCT:
        verdict = "model_common"
    elif same >= MODEL_COMMON_SAME_SIGN:
        verdict = "bias"
    else:
        verdict = "scenario"
    return {
        "n": n, "median": round(med, 2), "p25": round(_quantile(vals, 0.25), 2), "p75": round(_quantile(vals, 0.75), 2),
        "min": round(vals[0], 2), "max": round(vals[-1], 2), "within10": within10,
        "within25": sum(1 for v in vals if abs(v) <= FIT_WARN_PCT),
        "same_sign_pct": round(100.0 * same, 1), "sign": 1 if pos > neg else -1 if neg > pos else 0, "verdict": verdict,
    }


def flat_term(pairs: list[tuple[float | None, float | None]], *, base_fps: float = 30.0, min_share: float = 0.5) -> dict[str, Any] | None:
    """Detect a prediction term that only scales with fps (e.g. a flat CPU model).

    ``pairs`` = (predicted mW, fps). Returns the most common mW-per-``base_fps`` value when it
    covers at least ``min_share`` of the rows, else ``None``.
    """
    buckets: dict[int, list[float]] = {}
    n = 0
    for mw, fps in pairs:
        if mw is None or not fps:
            continue
        n += 1
        v = float(mw) * base_fps / float(fps)  # fps-normalised; 1 mW buckets absorb 29.97 vs 30 fps
        buckets.setdefault(round(v), []).append(v)
    if not n:
        return None
    vals = max(buckets.values(), key=len)
    if len(vals) / n < min_share or len(vals) < 3:
        return None
    return {"mw_at_base_fps": round(sum(vals) / len(vals), 1), "base_fps": base_fps, "count": len(vals), "n": n}


def correction_preview(rows: list[dict[str, Any]], factors: dict[str, float]) -> dict[str, Any]:
    """Total error if each predicted category were scaled by ``factors`` (CPU / IP / BW).

    ``rows`` carry ``meas.total``, ``meas.other`` and ``pred.{cpu,ip,bw}``. The unmodeled
    ``other`` rails stay out of the prediction, as in the registered model.
    """
    deltas = []
    for r in rows:
        pred, meas = r.get("pred") or {}, r.get("meas") or {}
        mt = meas.get("total")
        if not mt or any(pred.get(c) is None for c in ("cpu", "ip", "bw")):
            continue
        p = sum(float(pred[c]) * float(factors.get(c, 1.0)) for c in ("cpu", "ip", "bw"))
        deltas.append(100.0 * (p - float(mt)) / float(mt))
    st = bias_stats(deltas, min_n=1)
    return {"factors": {c: round(float(factors.get(c, 1.0)), 3) for c in ("cpu", "ip", "bw")},
            "median": st["median"], "within10": st["within10"], "n": st["n"],
            "max_abs": round(max((abs(d) for d in deltas), default=0.0), 1) if deltas else None}
