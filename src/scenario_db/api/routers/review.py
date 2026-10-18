from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.resource_limits import admission_slot
from scenario_db.api.services import review as svc
from scenario_db.api.services import review_risks as risks_svc
from scenario_db.config import get_settings

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/references", response_model=dict)
def references(project_ref: str, db: Session = Depends(get_db)):
    """Project review policy + per-variant power reference (previous project / explicit values)."""
    return svc.power_references(db, project_ref)


@router.get("/thermal-watch", response_model=dict)
def thermal_watch(
    project_ref: str,
    config_profile_ref: str | None = None,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("analyst", "writer", "admin")),
):
    """Thermal-watch variants: current power vs reference and the pre-computed power reduction menu / plans."""
    from scenario_db.api.schemas.timing_budget import TimingBudgetDvfsWhatIfRequest
    from scenario_db.api.services.timing_budget import analyze_dvfs_whatif_request

    def dvfs_rows(scenario_id: str, variant_id: str):
        req = TimingBudgetDvfsWhatIfRequest(scenario_id=scenario_id, variant_id=variant_id, shifts=[-2, -1],
                                            config_profile_ref=config_profile_ref)
        return analyze_dvfs_whatif_request(db, req)

    settings = get_settings()
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return svc.thermal_watch(db, project_ref, dvfs_whatif=dvfs_rows)


class RiskUpdateRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, pattern="^(open|watch|mitigating|accepted|closed)$")
    note: str | None = Field(default=None, max_length=2000)
    due_date: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears
    closure_evidence: str | None = Field(default=None, max_length=2000)


@router.get("/risks", response_model=list)
def risks(project_ref: str, db: Session = Depends(get_db)):
    """Project risk register (RPT-04): automatic rules from project reports + owner / status / note."""
    return risks_svc.list_risks(db, project_ref)


@router.patch("/risks/{risk_id}", response_model=dict)
def update_risk(
    risk_id: str,
    request: RiskUpdateRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """Owner / status / note of one risk; each change is kept in the row's history."""
    return risks_svc.update_risk(db, risk_id, owner=request.owner, status=request.status, note=request.note,
                                 due_date=request.due_date, closure_evidence=request.closure_evidence, user=principal.subject)


# ------------------------------------------------------------------- CPU-11 review snapshots
from scenario_db.api.schemas.cpu import CpuRebalanceSweepRequest  # noqa: E402
from scenario_db.api.services import review_cpu as cpu_snap  # noqa: E402


class CpuSnapshotRequest(BaseModel):
    project_ref: str
    request: CpuRebalanceSweepRequest
    note: str | None = Field(default=None, max_length=2000)


@router.get("/cpu-snapshots", response_model=list)
def cpu_snapshots(project_ref: str, include_inactive: bool = False, db: Session = Depends(get_db)):
    """CPU what-if results recorded for the project review (active per variant unless include_inactive)."""
    return cpu_snap.list_cpu_snapshots(db, project_ref, include_inactive=include_inactive)


@router.post("/cpu-snapshots", response_model=dict)
def create_cpu_snapshot(
    body: CpuSnapshotRequest,
    db: Session = Depends(get_db),
    principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """Re-run the SW growth sweep on the server and record its summary for the next project report."""
    settings = get_settings()
    with admission_slot("simulation", settings.simulation_max_concurrent_runs):
        return cpu_snap.record_cpu_snapshot(db, project_ref=body.project_ref, request=body.request, note=body.note,
                                            user=principal.subject)


@router.post("/cpu-snapshots/{snapshot_id}/withdraw", response_model=dict)
def withdraw_cpu_snapshot(
    snapshot_id: str,
    db: Session = Depends(get_db),
    _principal: ApiPrincipal = Depends(require_roles("writer", "admin")),
):
    """Withdraw a snapshot (kept for history, no longer quoted by new reports)."""
    return cpu_snap.withdraw_cpu_snapshot(db, snapshot_id)
