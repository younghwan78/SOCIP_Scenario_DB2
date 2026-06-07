from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.cdgm import CdgmResolveRequest, CdgmResolveResponse
from scenario_db.cdgm.service import resolve_cdgm_request

router = APIRouter(prefix="/cdgm", tags=["cdgm"])


@router.post("/resolve", response_model=CdgmResolveResponse)
def resolve_cdgm_arch_info_endpoint(
    request: CdgmResolveRequest,
    db: Session = Depends(get_db),
):
    return resolve_cdgm_request(db, request)
