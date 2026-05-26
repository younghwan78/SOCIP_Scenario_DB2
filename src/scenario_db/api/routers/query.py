from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.deps import get_db
from scenario_db.api.schemas.query import QueryFacetsResponse, QueryRequest, QueryResponse
from scenario_db.query_engine.service import QueryValidationError, build_facets, query_variants

router = APIRouter(prefix="/query", tags=["query"])


@router.get("/facets", response_model=QueryFacetsResponse)
def query_facets(db: Session = Depends(get_db)) -> QueryFacetsResponse:
    return build_facets(db)


@router.post("/variants", response_model=QueryResponse)
def query_variant_rows(request: QueryRequest, db: Session = Depends(get_db)) -> QueryResponse:
    try:
        return query_variants(db, request)
    except QueryValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors) from exc
