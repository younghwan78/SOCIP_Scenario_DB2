"""Prediction ↔ measurement calibration views (read-only)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.comparison.calibration import CATEGORIES, compare_split, measured_split, pct
from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import Prediction
from scenario_db.exceptions import NotFoundError


def _total(kpi: dict[str, Any] | None) -> dict[str, Any]:
    t = (kpi or {}).get("total_power_mw")
    if isinstance(t, dict):
        return {"mean": t.get("mean"), "std": t.get("std"), "p95": t.get("p95"), "ci_95": t.get("ci_95"), "n": t.get("n")}
    if isinstance(t, (int, float)):
        return {"mean": float(t), "std": None, "p95": None, "ci_95": None, "n": None}
    return {"mean": None, "std": None, "p95": None, "ci_95": None, "n": None}


def is_synthetic(provenance: dict[str, Any] | None) -> bool:
    """Generated fixture, not a silicon capture (see scripts/generate_rear_recording_evidence.py)."""
    p = provenance or {}
    return str(p.get("collection_method") or "").startswith("synthetic") or p.get("device_id") == "SYNTHETIC"


def _rail_map(db: Session, project_ref: str | None) -> tuple[dict[str, str], str | None]:
    q = db.query(SimConfigProfile)
    if project_ref:
        q = q.filter(SimConfigProfile.project_ref == project_ref)
    row = q.order_by(SimConfigProfile.version.desc()).first()
    if row is None:
        return {}, None
    return dict(row.rail_domain_map or {}), str(row.id)


def _sim_evidence(db: Session, scenario: str, variant: str) -> list[Evidence]:
    return (db.query(Evidence)
            .filter(Evidence.kind == "evidence.simulation", Evidence.scenario_ref == scenario, Evidence.variant_ref == variant)
            .order_by(Evidence.id).all())


def _current(db: Session, scenario: str, variant: str) -> Prediction | None:
    return (db.query(Prediction)
            .filter_by(scenario_ref=scenario, variant_ref=variant, status="current").one_or_none())


def _pred_split(power: dict[str, Any]) -> dict[str, float]:
    return {"cpu": float(power.get("cpu_mw") or 0.0), "ip": float(power.get("hw_mw") or 0.0),
            "bw": float(power.get("bw_mw") or 0.0)}


def coverage(db: Session, scenario_id: str) -> dict[str, dict[str, Any]]:
    """Per variant: simulation evidence count, real / synthetic measurement count, current prediction."""
    out: dict[str, dict[str, Any]] = {}

    def row(v: str) -> dict[str, Any]:
        return out.setdefault(v, {"simulation": 0, "measurement": 0, "synthetic": 0, "current_prediction": None})

    for kind, variant, prov in (db.query(Evidence.kind, Evidence.variant_ref, Evidence.provenance)
                                .filter(Evidence.scenario_ref == scenario_id).all()):
        if kind == "evidence.simulation":
            row(variant)["simulation"] += 1
        elif kind == "evidence.measurement":
            row(variant)["synthetic" if is_synthetic(prov) else "measurement"] += 1
    for p in db.query(Prediction).filter_by(scenario_ref=scenario_id, status="current").all():
        row(p.variant_ref)["current_prediction"] = {"id": p.id, "total_mw": (p.metrics or {}).get("power", {}).get("total_mw")}
    return out


def list_measurements(db: Session, *, scenario_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(Evidence).filter(Evidence.kind == "evidence.measurement")
    if scenario_id:
        q = q.filter(Evidence.scenario_ref == scenario_id)
    out = []
    for m in q.order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all():
        total = _total(m.kpi)
        cur = _current(db, m.scenario_ref, m.variant_ref)
        sims = _sim_evidence(db, m.scenario_ref, m.variant_ref)
        sim_total = _total(sims[-1].kpi)["mean"] if sims else None
        cur_total = cur.metrics["power"]["total_mw"] if cur else None
        ctx = m.execution_context or {}
        out.append({
            "id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref, "project_ref": m.project_ref,
            "measured_at": m.measured_at.isoformat() if m.measured_at else None,
            "silicon_rev": ctx.get("silicon_rev"), "sw_baseline_ref": m.sw_baseline_ref, "thermal": ctx.get("thermal"),
            "total": total, "fps": (m.kpi or {}).get("fps_effective"),
            "rails": len(m.vdd_power or {}), "synthetic": is_synthetic(m.provenance),
            "current_prediction": {"id": cur.id, "total_mw": cur_total, "delta_pct": pct(cur_total, total["mean"])} if cur else None,
            "simulation": {"id": sims[-1].id, "total_mw": sim_total, "delta_pct": pct(sim_total, total["mean"]), "count": len(sims)} if sims else None,
        })
    return out


def measurement_detail(db: Session, measurement_id: str) -> dict[str, Any]:
    m = db.get(Evidence, measurement_id)
    if m is None or m.kind != "evidence.measurement":
        raise NotFoundError(f"measurement evidence not found: {measurement_id}")
    rail_map, profile_ref = _rail_map(db, m.project_ref)
    split = measured_split(m.vdd_power, rail_map)
    total = _total(m.kpi)
    meas_cat = split["categories"]
    predictions: list[dict[str, Any]] = []
    cur = _current(db, m.scenario_ref, m.variant_ref)
    if cur is not None:
        pw = cur.metrics["power"]
        predictions.append({
            "kind": "current", "id": cur.id, "label": "등록 예측 (current)", "run_id": cur.exploration_run_ref,
            "selection_rule": cur.selection_rule, "statistic": cur.metrics.get("statistic"),
            "total_mw": pw["total_mw"], "delta_pct": pct(pw["total_mw"], total["mean"]),
            "split": _pred_split(pw), "rows": compare_split(_pred_split(pw), meas_cat),
        })
    for ev in _sim_evidence(db, m.scenario_ref, m.variant_ref):
        t = _total(ev.kpi)["mean"]
        pb = ev.power_breakdown or {}
        sp = None
        if isinstance(pb, dict) and pb.get("ip") is not None:
            def _mw(v: Any) -> float:
                return float(v.get("total_mw", 0.0)) if isinstance(v, dict) else float(v or 0.0)
            sp = {"cpu": _mw(pb.get("cpu")), "ip": _mw(pb.get("ip")), "bw": _mw(pb.get("memory"))}
        predictions.append({
            "kind": "simulation", "id": ev.id, "label": "Simulation evidence",
            "total_mw": t, "delta_pct": pct(t, total["mean"]), "split": sp,
            "rows": compare_split(sp, meas_cat) if sp else None,
        })
    sw = []
    for task in (m.sw_task_timing or []):
        if isinstance(task, dict):
            sw.append({k: task.get(k) for k in ("task", "mean_ms", "p95_ms", "max_ms", "min_ms", "count", "thread", "cluster", "timing_scope") if k in task})
    ctx = m.execution_context or {}
    return {
        "id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref, "project_ref": m.project_ref,
        "measured_at": m.measured_at.isoformat() if m.measured_at else None,
        "context": {k: ctx.get(k) for k in ("silicon_rev", "thermal", "power_state", "ambient_temp_c", "sw_baseline_ref")},
        "synthetic": is_synthetic(m.provenance), "derived_from": list(m.derived_from or []),
        "total": total, "fps": (m.kpi or {}).get("fps_effective"), "frame_latency": (m.kpi or {}).get("frame_latency_ms"),
        "measured": split, "rail_domain_map_ref": profile_ref,
        "unexplained_mw": None if total["mean"] is None else round(float(total["mean"]) - split["rail_total_mw"], 3),
        "categories": list(CATEGORIES), "predictions": predictions, "sw_tasks": sw,
        "cpu_clusters": m.cpu_breakdown,
    }
