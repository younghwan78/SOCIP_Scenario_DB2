"""예측 기준 (model basis): registry, active basis, promotion (draft -> trial -> promote)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from scenario_db.api.auth import ApiPrincipal, require_roles
from scenario_db.api.deps import get_db
from scenario_db.api.services import model_basis as svc

router = APIRouter(prefix="/bases", tags=["model basis"])


class BasisCreateRequest(BaseModel):
    project_ref: str
    config_profile_ref: str | None = None
    power_params_ref: str | None = None
    dvfs_table_ref: str | None = None
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    parent_ref: str | None = None


@router.get("")
def list_bases(project_ref: str, db: Session = Depends(get_db)):
    """Bases of a project, newest first, and the active one."""
    items = svc.list_bases(db, project_ref)
    return {"items": items, "active": next((b for b in items if b["status"] == "active"), None)}


@router.post("")
def create_basis(request: BasisCreateRequest, db: Session = Depends(get_db),
                 principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """New draft basis (same content in the project returns the existing one)."""
    return svc.create_basis(db, user=principal.subject, **request.model_dump())


@router.get("/{basis_id}")
def basis_detail(basis_id: str, db: Session = Depends(get_db)):
    """Basis with its components' content (profile run_config, power params summary, DVFS domains), input drift,
    trial summary and how many current predictions rest on it (UI: 기준 상세)."""
    return svc.basis_detail(db, basis_id)


@router.get("/{basis_id}/trial")
def get_trial(basis_id: str, db: Session = Depends(get_db)):
    return svc.get_trial(db, basis_id)


@router.post("/{basis_id}/trial")
def start_trial(basis_id: str, db: Session = Depends(get_db),
                principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """Snapshot the project's current predictions for a dry-run recompute under this draft basis."""
    return svc.start_trial(db, basis_id, principal.subject)


@router.post("/{basis_id}/trial/{prediction_id}")
def run_trial_item(basis_id: str, prediction_id: str, db: Session = Depends(get_db),
                   principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """Dry-run one prediction under the draft basis (a run is created; nothing is registered)."""
    from scenario_db.api.resource_limits import admission_slot
    from scenario_db.config import get_settings

    with admission_slot("simulation", get_settings().simulation_max_concurrent_runs):
        return svc.run_trial_item(db, basis_id, prediction_id, principal.subject)


@router.post("/{basis_id}/promote")
def promote_basis(basis_id: str, reason: str | None = None, db: Session = Depends(get_db),
                  principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """Register the successful trial items and make the basis active (one transaction)."""
    return svc.promote_basis(db, basis_id, principal.subject, reason=reason)


@router.post("/{basis_id}/activate")
def activate_basis(basis_id: str, db: Session = Depends(get_db),
                   principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    """Make a basis the default without re-registering predictions (first basis, or new runs only)."""
    return svc.activate_basis(db, basis_id, principal.subject)


@router.post("/{basis_id}/retire")
def retire_basis(basis_id: str, db: Session = Depends(get_db),
                 principal: ApiPrincipal = Depends(require_roles("writer", "admin"))):
    return svc.retire_basis(db, basis_id)
