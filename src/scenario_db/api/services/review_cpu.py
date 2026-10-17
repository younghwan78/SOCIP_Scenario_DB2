"""CPU what-if results recorded for the project review (CPU-11).

``record_cpu_snapshot`` re-runs the SW growth sweep on the server from the request, keeps a compact
summary (tolerance, binding limit, OPP step, current / best power per growth, the best distribution at
the first growth, CPU-caused BW power) and supersedes the previous active snapshot of the variant.
Project reports freeze the active snapshots into their ``cpu`` section.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.schemas.cpu import CpuRebalanceSweepRequest
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.exploration import ReviewCpuSnapshot
from scenario_db.db.repositories.evidence import get_evidence
from scenario_db.exceptions import NotFoundError, UnprocessableError


def sweep_summary(sweep: dict[str, Any]) -> dict[str, Any]:
    """Compact, report-sized view of a ``run_cpu_rebalance_sweep`` result."""
    pts = sweep.get("points") or []
    lim = sweep.get("limits") or {}
    p0 = pts[0] if pts else {}
    best0 = p0.get("best") or {}
    rows = []
    for p in pts:
        ref, best = p.get("reference") or {}, p.get("best") or {}
        rows.append({"growth": p["growth"], "ref_mw": ref.get("total_mw"), "best_mw": best.get("total_mw"),
                     "ref_feasible": ref.get("feasible"), "bw_mw": p.get("bw_mw"), "cpu_bw_mbs": p.get("cpu_bw_mbs"),
                     "ref_mhz": ref.get("mhz"), "best_mhz": best.get("mhz"), "winner": p.get("winner")})
    return {
        "tolerance": lim.get("tolerance"), "binding": lim.get("binding"), "timing_at": lim.get("timing_at"),
        "opp_step": lim.get("opp_step"), "opp_step_best_mw": lim.get("opp_step_best_mw"),
        "growth_range": [pts[0]["growth"], pts[-1]["growth"]] if pts else None,
        "points": rows,
        "best_at_start": {"total_mw": best0.get("total_mw"), "moved": best0.get("moved") or [],
                          "delta_mw": (round(best0["total_mw"] - p0["reference"]["total_mw"], 2)
                                       if best0.get("total_mw") is not None and (p0.get("reference") or {}).get("total_mw") is not None else None),
                          "mhz": best0.get("mhz")},
        "bw_power": sweep.get("bw_power"), "events": (sweep.get("events") or [])[:12],
    }


def snapshot_view(row: ReviewCpuSnapshot) -> dict[str, Any]:
    return {"id": row.id, "project_ref": row.project_ref, "scenario_id": row.scenario_ref, "variant_id": row.variant_ref,
            "profile_ref": row.profile_ref, "power_params_ref": row.power_params_ref,
            "base_power_params_ref": row.base_power_params_ref, "status": row.status, "note": row.note,
            "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None,
            "summary": row.summary, "request": row.request}


def record_cpu_snapshot(db: Session, *, project_ref: str, request: CpuRebalanceSweepRequest, note: str | None,
                        user: str | None) -> dict[str, Any]:
    from scenario_db.api.services.cpu import run_cpu_rebalance_sweep
    from scenario_db.api.services.calibration import data_origin

    if db.get(Project, project_ref) is None:
        raise NotFoundError(f"project not found: {project_ref}")
    if not request.cpu_profile_ref or request.cpu_profile is not None:
        raise UnprocessableError("a review snapshot needs a stored measurement profile (cpu_profile_ref)")
    prof = get_evidence(db, request.cpu_profile_ref)
    if prof is None or not prof.scenario_ref or not prof.variant_ref:
        raise NotFoundError(f"measurement profile not found: {request.cpu_profile_ref}")
    scen = db.get(Scenario, prof.scenario_ref)
    if scen is None or scen.project_ref != project_ref:
        raise UnprocessableError(f"profile {request.cpu_profile_ref} is not a measurement of project {project_ref}")
    sweep = run_cpu_rebalance_sweep(db, request)
    summary = sweep_summary(sweep) | {"profile_origin": data_origin(prof.provenance)}
    now = datetime.now(UTC)
    for old in (db.query(ReviewCpuSnapshot).filter_by(project_ref=project_ref, scenario_ref=prof.scenario_ref,
                                                       variant_ref=prof.variant_ref, status="active").all()):
        old.status = "superseded"
    row = ReviewCpuSnapshot(id=f"CPUSNAP-{uuid.uuid4().hex[:12]}", project_ref=project_ref, scenario_ref=prof.scenario_ref,
                            variant_ref=prof.variant_ref, profile_ref=request.cpu_profile_ref,
                            power_params_ref=request.power_params_ref, base_power_params_ref=request.base_power_params_ref,
                            status="active", note=(note or "").strip() or None, request=request.model_dump(mode="json"),
                            summary=summary, created_by=user, created_at=now)
    db.add(row)
    db.commit()
    return snapshot_view(row)


def list_cpu_snapshots(db: Session, project_ref: str, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    q = db.query(ReviewCpuSnapshot).filter(ReviewCpuSnapshot.project_ref == project_ref)
    if not include_inactive:
        q = q.filter(ReviewCpuSnapshot.status == "active")
    return [snapshot_view(r) for r in q.order_by(ReviewCpuSnapshot.variant_ref, ReviewCpuSnapshot.created_at.desc()).all()]


def withdraw_cpu_snapshot(db: Session, snapshot_id: str) -> dict[str, Any]:
    row = db.get(ReviewCpuSnapshot, snapshot_id)
    if row is None:
        raise NotFoundError(f"cpu snapshot not found: {snapshot_id}")
    row.status = "withdrawn"
    db.commit()
    return snapshot_view(row)
