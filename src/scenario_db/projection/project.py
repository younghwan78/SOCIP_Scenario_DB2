"""Apply a calibration + cluster scaling to produce projected V evidence."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from scenario_db.projection.calibrate import rail_scalar
from scenario_db.projection.models import Calibration, ProjectionRecipe

_SLUG_RE = re.compile(r"[^a-zA-Z0-9.]+")
_SCALE_KEYS = ("mean_ms", "p50_ms", "p95_ms", "max_ms")


def project_power(v_sim: dict, cal: Calibration, *, scale_ip_breakdown: bool) -> dict:
    """Scale V calculation power by U-derived factors.

    Returns {"kpi", "vdd_power", "ip_breakdown", "trace"} with only the keys
    that V actually carried. Unscaled metrics are passed through unchanged and
    recorded so the projection is auditable.
    """
    trace: dict = {"scaled_kpi": {}, "scaled_rails": {}, "unscaled_kpi": [], "ip_breakdown": None}
    out: dict = {}

    # KPI (flat numbers only — evidence.simulation kpi is numeric)
    v_kpi = v_sim.get("kpi") or {}
    proj_kpi: dict = {}
    for key, value in v_kpi.items():
        if not isinstance(value, (int, float)):
            proj_kpi[key] = value
            continue
        factor = cal.kpi_factors.get(key)
        if factor is None:
            proj_kpi[key] = value
            trace["unscaled_kpi"].append(key)
        else:
            proj_kpi[key] = round(value * factor, 6)
            trace["scaled_kpi"][key] = {"base": value, "factor": factor, "projected": proj_kpi[key]}
    if proj_kpi:
        out["kpi"] = proj_kpi

    # vdd_power: per-rail factor, fall back to total power factor.
    v_vdd = v_sim.get("vdd_power") or {}
    proj_vdd: dict = {}
    for rail, entry in v_vdd.items():
        # A measured 0 mW rail (gated domain) yields a legitimate 0.0 factor;
        # membership, not truthiness, decides the fallback to the total factor.
        factor = (
            cal.rail_factors[rail]
            if rail in cal.rail_factors
            else cal.total_power_factor
        )
        if factor is None or not isinstance(entry, dict):
            proj_vdd[rail] = entry
            continue
        scaled = {
            k: (round(v * factor, 6) if isinstance(v, (int, float)) else v)
            for k, v in entry.items()
        }
        proj_vdd[rail] = scaled
        trace["scaled_rails"][rail] = {
            "factor": factor,
            "source": "rail" if rail in cal.rail_factors else "total",
        }
    if proj_vdd:
        out["vdd_power"] = proj_vdd

    # ip_breakdown: uniform scaling by the global power factor (documented approx).
    v_ip = v_sim.get("ip_breakdown") or []
    if v_ip:
        if scale_ip_breakdown and cal.total_power_factor:
            f = cal.total_power_factor
            scaled_ips = []
            for ip in v_ip:
                ip2 = dict(ip)
                if isinstance(ip2.get("power_mW"), (int, float)):
                    ip2["power_mW"] = round(ip2["power_mW"] * f, 6)
                if isinstance(ip2.get("submodules"), list):
                    ip2["submodules"] = [
                        {**s, "power_mW": round(s["power_mW"] * f, 6)}
                        if isinstance(s.get("power_mW"), (int, float)) else s
                        for s in ip2["submodules"]
                    ]
                scaled_ips.append(ip2)
            out["ip_breakdown"] = scaled_ips
            trace["ip_breakdown"] = {"mode": "uniform_total_factor", "factor": f}
        else:
            out["ip_breakdown"] = v_ip
            trace["ip_breakdown"] = {"mode": "passthrough"}

    return {**out, "trace": trace}


def project_sw_timing(u_meas: dict, recipe: ProjectionRecipe) -> dict:
    """Scale U's measured sw_task_timing by per-cluster time_scale.

    Returns {"sw_task_timing": [...], "trace": {...}}.
    """
    u_tasks = u_meas.get("sw_task_timing") or []
    trace: dict = {"task_scales": {}, "missing_cluster_scale": []}
    out_tasks: list[dict] = []
    for task in u_tasks:
        cluster = task.get("cluster")
        scaling = recipe.cluster_scaling.get(cluster) if cluster else None
        scale = scaling.time_scale if scaling else 1.0
        if scaling is None:
            trace["missing_cluster_scale"].append(task.get("task"))
        projected = dict(task)
        for k in _SCALE_KEYS:
            if isinstance(projected.get(k), (int, float)):
                projected[k] = round(projected[k] * scale, 6)
        out_tasks.append(projected)
        trace["task_scales"][task.get("task")] = {"cluster": cluster, "time_scale": scale}
    return {"sw_task_timing": out_tasks, "trace": trace}


def generate_projection_id(recipe: ProjectionRecipe) -> str:
    t = recipe.target
    parts = ["sim", _slug(t.scenario_ref), _slug(t.variant_ref), _slug(t.silicon_rev), "projection"]
    return "-".join(p for p in parts if p)


def _slug(value: str) -> str:
    return _SLUG_RE.sub("-", value).strip("-")


def assemble_projection(
    recipe: ProjectionRecipe,
    u_meas: dict,
    u_sim: dict,
    v_sim: dict,
    cal: Calibration,
) -> dict:
    target = recipe.target
    power = project_power(v_sim, cal, scale_ip_breakdown=recipe.scale_ip_breakdown)
    sw = project_sw_timing(u_meas, recipe)

    derived_from = [
        eid
        for eid in (u_meas.get("id"), u_sim.get("id"), v_sim.get("id"))
        if eid
    ]

    doc: dict = {
        "id": target.id or generate_projection_id(recipe),
        "schema_version": target.schema_version,
        "kind": "evidence.simulation",
        "scenario_ref": target.scenario_ref,
        "variant_ref": target.variant_ref,
        "project_ref": target.project_ref,
        "derived_from": derived_from,
        "execution_context": {
            "silicon_rev": target.silicon_rev,
            "sw_baseline_ref": target.sw_baseline_ref,
            "thermal": (v_sim.get("execution_context") or {}).get("thermal", "unknown"),
            "method": "projection",
        },
        "run": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": "scenario_db.projection",
            "source": "estimated",
        },
        "aggregation": {"strategy": "projection"},
        "calculation_trace": {
            "projection": {
                "calibration": cal.to_trace(),
                "power": power["trace"],
                "sw_timing": sw["trace"],
                "cluster_scaling": {
                    c: s.time_scale for c, s in recipe.cluster_scaling.items()
                },
                "notes": recipe.notes,
            }
        },
    }

    if "kpi" in power:
        doc["kpi"] = power["kpi"]
    if "vdd_power" in power:
        doc["vdd_power"] = power["vdd_power"]
    if "ip_breakdown" in power:
        doc["ip_breakdown"] = power["ip_breakdown"]
    if sw["sw_task_timing"]:
        doc["sw_task_timing"] = sw["sw_task_timing"]

    return doc
