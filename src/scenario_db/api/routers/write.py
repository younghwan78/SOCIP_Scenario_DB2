from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.auth import MutationPrincipal, require_mutation_principal
from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache
from scenario_db.api.schemas.write import (
    ApplyWriteResponse,
    DiffPreviewResponse,
    StageWriteRequest,
    StageWriteResponse,
    ValidateWriteResponse,
    WriteBatchResponse,
)
from scenario_db.write.service import (
    apply_batch,
    diff_batch,
    get_batch_or_404,
    stage_write,
    validate_batch,
)

router = APIRouter(
    prefix="/write",
    tags=["write"],
    dependencies=[Depends(require_mutation_principal)],
)


@router.post("/staging", response_model=StageWriteResponse)
def create_staging_batch(
    request: StageWriteRequest,
    db: Session = Depends(get_db),
    principal: MutationPrincipal = Depends(require_mutation_principal),
):
    authenticated_request = request.model_copy(update={"actor": principal.subject})
    return stage_write(db, authenticated_request)


@router.get("/staging/{batch_id}", response_model=WriteBatchResponse)
def get_staging_batch(batch_id: str, db: Session = Depends(get_db)):
    return get_batch_or_404(db, batch_id)


@router.post("/staging/{batch_id}/validate", response_model=ValidateWriteResponse)
def validate_staging_batch(batch_id: str, db: Session = Depends(get_db)):
    return validate_batch(db, batch_id)


@router.post("/staging/{batch_id}/diff", response_model=DiffPreviewResponse)
def preview_staging_diff(batch_id: str, db: Session = Depends(get_db)):
    return diff_batch(db, batch_id)


@router.post("/staging/{batch_id}/apply", response_model=ApplyWriteResponse)
def apply_staging_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    rule_cache: RuleCache = Depends(get_rule_cache),
):
    return apply_batch(db, batch_id, rule_cache=rule_cache)
