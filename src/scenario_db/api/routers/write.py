from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
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

router = APIRouter(prefix="/write", tags=["write"])


@router.post("/staging", response_model=StageWriteResponse)
def create_staging_batch(request: StageWriteRequest, db: Session = Depends(get_db)):
    return stage_write(db, request)


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
def apply_staging_batch(batch_id: str, db: Session = Depends(get_db)):
    return apply_batch(db, batch_id)
