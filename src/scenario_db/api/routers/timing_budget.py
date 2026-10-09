from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, audit_user, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size, enforce_timeline_frame_limit
from scenario_db.api.schemas.timing_budget import (
    TimingBudgetDistributionRequest,
    TimingBudgetDvfsWhatIfRequest,
    TimingBudgetEvidenceRequest,
    TimingBudgetFleetRequest,
    TimingBudgetFleetResponse,
    TimingBudgetRegisterRequest,
    TimingBudgetRequest,
    TimingBudgetResponse,
)
from scenario_db.api.services.timing_budget import (
    analyze_dvfs_whatif_request,
    analyze_timing_budget_fleet,
    analyze_timing_budget_request,
    interval_distribution_request,
    register_condition,
    save_condition_evidence,
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


@router.post("/dvfs-whatif", response_model=dict)
def timing_budget_dvfs_whatif(
    request: TimingBudgetDvfsWhatIfRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """DVFS domain level +/-k: SW slack, power, BW and verdict per domain and shift (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.options.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return analyze_dvfs_whatif_request(db, request)


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


@router.post("/interval-distribution", response_model=dict)
def timing_budget_interval_distribution(
    request: TimingBudgetDistributionRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Output interval / latency spread under per-frame SW variance (seeded trials, read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return interval_distribution_request(db, request)


@router.post("/register", response_model=dict)
def timing_budget_register(
    request: TimingBudgetRegisterRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """Register this condition as the variant's current prediction (rule manual:timing-budget)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.options.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return register_condition(db, request, principal.subject)


@router.post("/evidence", response_model=dict)
def timing_budget_save_evidence(
    request: TimingBudgetEvidenceRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Keep this condition's budget run as simulation evidence (same condition = same evidence id)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    enforce_timeline_frame_limit(request.options.frames, settings.simulation_max_timeline_frames)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return save_condition_evidence(db, request, audit_user(principal))
