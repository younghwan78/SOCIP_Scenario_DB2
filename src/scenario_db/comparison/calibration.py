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
from typing import Any

CATEGORIES = ("cpu", "ip", "bw", "other")
_DOMAIN_TO_CATEGORY = {"CPU": "cpu", "MIF": "bw", "MEM": "bw", "DRAM": "bw"}
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
