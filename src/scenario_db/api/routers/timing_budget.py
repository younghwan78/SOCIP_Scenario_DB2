from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.timing_budget import (
    TimingBudgetFleetRequest,
    TimingBudgetFleetResponse,
    TimingBudgetRequest,
    TimingBudgetResponse,
)
from scenario_db.api.services.timing_budget import (
    analyze_timing_budget_fleet,
    analyze_timing_budget_request,
)
from scenario_db.config import get_settings

router = APIRouter(prefix="/timing-budget", tags=["timing budget"])


@router.post("/variant", response_model=TimingBudgetResponse)
def timing_budget_variant(
    request: TimingBudgetRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """RT 25% rule, NRT/GDC SW-derived budgets, output cadence, power and BW (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.options.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return analyze_timing_budget_request(db, request)


@router.post("/fleet", response_model=TimingBudgetFleetResponse)
def timing_budget_fleet(
    request: TimingBudgetFleetRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Per-variant summary rows for one scenario (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.options.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return analyze_timing_budget_fleet(db, request)
