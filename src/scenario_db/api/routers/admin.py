"""Operational admin endpoints (cache refresh 등).

기본 비활성 — SCENARIO_DB_ADMIN_ENDPOINTS_ENABLED=true 일 때만
create_app()이 이 라우터를 등록한다 (VPN 등 신뢰 네트워크 전용).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from scenario_db.api.auth import require_mutation_principal
from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_mutation_principal)],
)


@router.post("/cache/refresh")
def refresh_rule_cache(
    db: Session = Depends(get_db),
    cache: RuleCache = Depends(get_rule_cache),
):
    """RuleCache를 DB에서 다시 로드한다.

    ETL(`python -m scenario_db.etl.loader`)이 decision.issue / decision.gate_rule을
    직접 적재한 뒤 API 재시작 없이 캐시를 갱신하는 용도. 단일 워커 기준이며,
    멀티 워커 운영 시에는 워커별로 호출이 필요하다.
    """
    cache.invalidate_all(db)
    from scenario_db.query_engine.service import invalidate_facets_cache

    invalidate_facets_cache()
    return {
        "loaded": cache.loaded,
        "issues": len(cache.issues),
        "gate_rules": len(cache.gate_rules),
        "load_error": cache.load_error,
    }
