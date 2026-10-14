"""Explicit What-if operations use the same admission limits and roles as Timing Budget."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.scenario_whatif import WhatIfExperimentRequest, WhatIfPlanRequest, WhatIfPreviewRequest, WhatIfScope
from scenario_db.api.services import scenario_whatif as service
from scenario_db.config import get_settings

router = APIRouter(prefix="/scenario-whatif", tags=["scenario what-if"])
read_access = require_roles("reader", "analyst", "writer", "admin")
calculate_access = require_roles("analyst", "writer", "admin")


@router.get("/targets")
def targets(project_ref: str = Query(..., min_length=1, max_length=160),
            scenario_id: str = Query(..., min_length=1, max_length=160),
            variant_id: str = Query(..., min_length=1, max_length=160), db: Session = Depends(get_db),
            _principal: ApiPrincipal = Depends(read_access)):
    return service.targets(db, WhatIfScope(project_ref=project_ref, scenario_id=scenario_id, variant_id=variant_id))


@router.post("/plan")
def plan(request: WhatIfPlanRequest, db: Session = Depends(get_db),
         _principal: ApiPrincipal = Depends(calculate_access)):
    settings = _limits(request)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return service.plan(db, request)


def _limits(request):
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    condition = request.preview_request if isinstance(request, WhatIfExperimentRequest) else request
    enforce_timeline_frame_limit(max(condition.options.frames, condition.options.timeline_frames + 4,
                                    condition.config.timeline_frame_count), settings.simulation_max_timeline_frames)
    return settings


@router.post("/preview")
def preview(request: WhatIfPreviewRequest, db: Session = Depends(get_db),
            _principal: ApiPrincipal = Depends(calculate_access)):
    settings = _limits(request)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return service.preview(db, request)


@router.post("/experiments", status_code=201)
def save(request: WhatIfExperimentRequest, db: Session = Depends(get_db),
         principal: ApiPrincipal = Depends(calculate_access)):
    settings = _limits(request)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return service.save_experiment(db, request, principal.subject)


@router.get("/experiments")
def experiments(project_ref: str = Query(..., min_length=1, max_length=160),
                scenario_id: str | None = Query(None, min_length=1, max_length=160),
                variant_id: str | None = Query(None, min_length=1, max_length=160),
                limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                db: Session = Depends(get_db), principal: ApiPrincipal = Depends(read_access)):
    return service.list_experiments(db, principal.subject, project_ref, scenario_id=scenario_id,
                                    variant_id=variant_id, limit=limit, offset=offset)


@router.get("/experiments/{experiment_id}")
def experiment(experiment_id: str, db: Session = Depends(get_db), principal: ApiPrincipal = Depends(read_access)):
    return service.get_experiment(db, experiment_id, principal.subject)
