"""Compute correction factors from a project's own sim vs measurement.

We can only calibrate on metrics both sides expose with comparable semantics:

- ``kpi.total_power_mw``      (sim: flat number, meas: MeasuredKpi.mean)
- ``vdd_power[rail]``         (per-rail mean power, where rail names overlap)
- any other numeric ``kpi``   present and scalar on both sides

CPU-cluster power (meas) and per-IP power (sim) do not align one-to-one, so
they are not calibrated here; per-IP projection uses the global power factor.
"""
from __future__ import annotations

from scenario_db.projection.models import Calibration

# priority order of keys used to pull a scalar power from a vdd_power rail entry.
# total_mw is the simulation runner's per-rail total (core_mw + bw_mw).
_RAIL_KEYS = ("mean_mw", "power_mw", "total_mw", "power", "mean")


def kpi_scalar(value: object) -> float | None:
    """Representative scalar for a KPI value (MeasuredKpi.mean or a flat number)."""
    if isinstance(value, dict):
        mean = value.get("mean")
        return float(mean) if isinstance(mean, (int, float)) else None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def rail_scalar(entry: object) -> float | None:
    """Representative scalar power for a vdd_power rail entry."""
    if isinstance(entry, (int, float)):
        return float(entry)
    if isinstance(entry, dict):
        for key in _RAIL_KEYS:
            if isinstance(entry.get(key), (int, float)):
                return float(entry[key])
    return None


def _factor(sim: float | None, meas: float | None) -> float | None:
    if sim is None or meas is None or sim == 0:
        return None
    return meas / sim


def compute_calibration(u_sim: dict, u_meas: dict) -> Calibration:
    cal = Calibration()

    sim_kpi = u_sim.get("kpi") or {}
    meas_kpi = u_meas.get("kpi") or {}

    # total power
    sim_total = kpi_scalar(sim_kpi.get("total_power_mw"))
    meas_total = kpi_scalar(meas_kpi.get("total_power_mw"))
    tf = _factor(sim_total, meas_total)
    if tf is not None:
        cal.total_power_factor = round(tf, 6)
        cal.detail["total_power_mw"] = {"sim": sim_total, "meas": meas_total, "factor": cal.total_power_factor}

    # any overlapping numeric KPI (incl. total_power_mw, recorded in kpi_factors too)
    for key in set(sim_kpi) & set(meas_kpi):
        s = kpi_scalar(sim_kpi.get(key))
        m = kpi_scalar(meas_kpi.get(key))
        f = _factor(s, m)
        if f is not None:
            cal.kpi_factors[key] = round(f, 6)
            cal.detail.setdefault(key, {"sim": s, "meas": m, "factor": round(f, 6)})

    # per-rail power
    sim_vdd = u_sim.get("vdd_power") or {}
    meas_vdd = u_meas.get("vdd_power") or {}
    for rail in set(sim_vdd) & set(meas_vdd):
        s = rail_scalar(sim_vdd.get(rail))
        m = rail_scalar(meas_vdd.get(rail))
        f = _factor(s, m)
        if f is not None:
            cal.rail_factors[rail] = round(f, 6)
            cal.detail[f"rail:{rail}"] = {"sim": s, "meas": m, "factor": round(f, 6)}

    return cal
