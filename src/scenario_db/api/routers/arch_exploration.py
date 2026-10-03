from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.arch_exploration import (
    ArchExplorationRunRequest,
    ArchReportRequest,
    PowerOptionReviewRequest,
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
    view: Literal["full", "summary"] = "full",
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """SW statistic x growth (simulated) x DVFS headroom x compression (analytic) per variant; persisted."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.spec.timing.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        result = svc.run_exploration(db, request, principal.subject)
    if view == "summary":
        result = result | {"variants": [svc.variant_summary(v) for v in result["variants"]], "view": "summary"}
    return result


@router.get("/exploration/runs")
def list_runs(
    scenario_type: str | None = None, project_ref: str | None = None,
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
):
    return svc.list_runs(db, scenario_type=scenario_type, project_ref=project_ref, limit=limit)


@router.get("/exploration/runs/{run_id}")
def get_run(run_id: str, view: Literal["full", "summary"] = "full", db: Session = Depends(get_db)):
    """view=summary: per-variant list fields only (UI); a variant's full summary via /variants/{scenario}/{variant}."""
    return svc.run_summary(db, run_id) if view == "summary" else svc.run_detail(svc.get_run(db, run_id))


@router.get("/exploration/runs/{run_id}/variants/{scenario_id}/{variant_id}")
def get_run_variant(run_id: str, scenario_id: str, variant_id: str, db: Session = Depends(get_db)):
    return svc.run_variant(db, run_id, scenario_id, variant_id)


@router.get("/exploration/runs/{run_id}/manifest")
def get_run_manifest(run_id: str, db: Session = Depends(get_db)):
    """Resolved inputs (config, DVFS, pipeline, variant, IP capabilities) per variant, content-addressed."""
    return svc.run_manifest(db, run_id)


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


# ------------------------------------------------------------------- power options (IQ review)
@router.get("/power-options/reviews")
def list_option_reviews(project_ref: str | None = None, scenario_id: str | None = None,
                        db: Session = Depends(get_db)):
    return svc.list_option_reviews(db, project_ref=project_ref, scenario_id=scenario_id)


@router.put("/power-options/reviews")
def set_option_review(
    request: PowerOptionReviewRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """candidate -> iq_eval -> adopted / rejected. Adopting does not change any variant:
    add the knob value / IP mode to the formal variant in authoring."""
    return svc.set_option_review(db, request, principal.subject)


@router.get("/predictions/{prediction_id}")
def get_prediction(prediction_id: str, db: Session = Depends(get_db)):
    return svc.get_prediction(db, prediction_id)


# ------------------------------------------------------------------- model status
@router.get("/model-status")
def model_status(project_ref: str | None = None, db: Session = Depends(get_db)):
    """Engine rev, DVFS tables and real/synthetic measurements behind the displayed numbers."""
    return svc.model_status(db, project_ref=project_ref)


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


@router.get("/reports/{report_id}/xlsx")
def get_report_xlsx(report_id: str, db: Session = Depends(get_db)):
    """Frozen report tables as an Excel workbook (one sheet per table)."""
    data, filename = svc.report_xlsx(db, report_id)
    return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/{report_id}/package")
def get_report_package(report_id: str, db: Session = Depends(get_db)):
    """Review package: frozen report.html + cover.html + manifest.json (works offline)."""
    data, filename = svc.report_package(db, report_id)
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/{report_id}/stale")
def report_stale(report_id: str, db: Session = Depends(get_db)):
    return svc.report_stale(db, report_id)


@router.patch("/reports/{report_id}")
def set_status(
    report_id: str, request: ReportStatusRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    return svc.set_report_status(db, report_id, request.status, reviewer=request.reviewer, note=request.note,
                                 user=principal.subject)
