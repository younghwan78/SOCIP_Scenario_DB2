"""Close the loop: compare a projection against the target's real measurement.

When V silicon arrives and V is measured, this quantifies how well the
projection held up — the actual validation result of the whole pipeline.
"""
from __future__ import annotations

from scenario_db.projection.calibrate import kpi_scalar, rail_scalar


def _pct_error(projected: float, measured: float) -> float | None:
    if measured == 0:
        return None
    return round((projected - measured) / measured * 100.0, 3)


def compute_projection_error(projected: dict, v_meas: dict) -> dict:
    """Per-metric projected-vs-measured comparison.

    Returns {"kpi": {metric: {projected, measured, pct_error}}, "vdd_power": {...},
    "summary": {n, mean_abs_pct_error, max_abs_pct_error, worst_metric}}.
    """
    report: dict = {"kpi": {}, "vdd_power": {}}
    abs_errors: list[tuple[str, float]] = []

    proj_kpi = projected.get("kpi") or {}
    meas_kpi = v_meas.get("kpi") or {}
    for key in set(proj_kpi) & set(meas_kpi):
        p = kpi_scalar(proj_kpi.get(key))
        m = kpi_scalar(meas_kpi.get(key))
        if p is None or m is None:
            continue
        err = _pct_error(p, m)
        report["kpi"][key] = {"projected": p, "measured": m, "pct_error": err}
        if err is not None:
            abs_errors.append((f"kpi.{key}", abs(err)))

    proj_vdd = projected.get("vdd_power") or {}
    meas_vdd = v_meas.get("vdd_power") or {}
    for rail in set(proj_vdd) & set(meas_vdd):
        p = rail_scalar(proj_vdd.get(rail))
        m = rail_scalar(meas_vdd.get(rail))
        if p is None or m is None:
            continue
        err = _pct_error(p, m)
        report["vdd_power"][rail] = {"projected": p, "measured": m, "pct_error": err}
        if err is not None:
            abs_errors.append((f"vdd.{rail}", abs(err)))

    if abs_errors:
        worst_metric, worst = max(abs_errors, key=lambda x: x[1])
        report["summary"] = {
            "n": len(abs_errors),
            "mean_abs_pct_error": round(sum(e for _, e in abs_errors) / len(abs_errors), 3),
            "max_abs_pct_error": round(worst, 3),
            "worst_metric": worst_metric,
        }
    else:
        report["summary"] = {"n": 0}
    return report
