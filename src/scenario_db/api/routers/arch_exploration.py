from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.arch_exploration import (
    ArchExplorationRunRequest,
    ArchReportRequest,
    PromoteRequest,
    ReportStatusRequest,
)
from scenario_db.api.services import arch_exploration as svc
from scenario_db.config import get_settings

router = APIRouter(prefix="/arch", tags=["architecture exploration"])


# ------------------------------------------------------------------- exploration
@router.post("/exploration/runs")
def create_run(
    request: ArchExplorationRunRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """SW statistic x growth (simulated) x DVFS headroom x compression (analytic) per variant; persisted."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.spec.timing.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return svc.run_exploration(db, request, principal.subject)


@router.get("/exploration/runs")
def list_runs(scenario_type: str | None = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return svc.list_runs(db, scenario_type=scenario_type, limit=limit)


@router.get("/exploration/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    return svc.run_detail(svc.get_run(db, run_id))


# ------------------------------------------------------------------- predictions
@router.post("/predictions/promote")
def promote(
    request: PromoteRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """Register run cases as current predictions (default: lowest-power eligible case)."""
    return svc.promote(db, request, principal.subject)


@router.get("/predictions/board")
def board(scenario_id: str | None = None, project_ref: str | None = None, db: Session = Depends(get_db)):
    return svc.board(db, scenario_id=scenario_id, project_ref=project_ref)


@router.get("/predictions/history")
def history(scenario_id: str, variant_id: str, db: Session = Depends(get_db)):
    return svc.history(db, scenario_id, variant_id)


@router.get("/predictions/compare")
def compare(
    old_id: str | None = None, new_id: str | None = None,
    scenario_id: str | None = None, variant_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Power change attribution (default: current vs the prediction it superseded)."""
    return svc.compare(db, old_id=old_id, new_id=new_id, scenario_id=scenario_id, variant_id=variant_id)


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, db: Session = Depends(get_db)):
    return svc.get_prediction(db, prediction_id)


# ------------------------------------------------------------------- reports
@router.post("/reports")
def create_report(
    request: ArchReportRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    return svc.create_report(db, request, principal.subject)


@router.get("/reports")
def list_reports(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return svc.list_reports(db, limit)


@router.get("/reports/{report_id}")
def get_report(report_id: str, db: Session = Depends(get_db)):
    return svc.report_detail(svc.get_report(db, report_id))


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(report_id: str, db: Session = Depends(get_db)):
    return HTMLResponse(svc.get_report(db, report_id).rendered_html)


@router.get("/reports/{report_id}/stale")
def report_stale(report_id: str, db: Session = Depends(get_db)):
    return svc.report_stale(db, report_id)


@router.patch("/reports/{report_id}")
def set_status(
    report_id: str, request: ReportStatusRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    return svc.set_report_status(db, report_id, request.status)
