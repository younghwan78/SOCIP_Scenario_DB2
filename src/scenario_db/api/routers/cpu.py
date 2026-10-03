from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot, enforce_request_size
from scenario_db.api.schemas.cpu import CpuRebalanceRequest, CpuSweepRequest, CpuWhatIfRequest, CpuWhatIfResponse
from scenario_db.api.services.cpu import list_cpu_inputs, run_cpu_rebalance, run_cpu_sweep, run_cpu_whatif
from scenario_db.config import get_settings

router = APIRouter(prefix="/cpu", tags=["cpu"])


@router.get("/inputs", response_model=dict)
def cpu_inputs(
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """CPU topologies (power_model_params with cpu.clusters) and measurements with a CPU profile."""
    return list_cpu_inputs(db)


@router.post("/whatif", response_model=CpuWhatIfResponse)
def cpu_whatif_route(
    request: CpuWhatIfRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Per-frame placement / frequency what-if (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return run_cpu_whatif(db, request)


@router.post("/sweep", response_model=CpuWhatIfResponse)
def cpu_sweep_route(
    request: CpuSweepRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """EAS + schedutil reproduction of a measured CPU profile and an automatic cpuset / uclamp sweep (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return run_cpu_sweep(db, request)


@router.post("/rebalance", response_model=CpuWhatIfResponse)
def cpu_rebalance_route(
    request: CpuRebalanceRequest,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Split movable tasks over a cluster pool (cpuset) for the lowest CPU + DSU power within budgets (read-only)."""
    settings = get_settings()
    enforce_request_size(request, settings.exploration_max_request_bytes)
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return run_cpu_rebalance(db, request)
