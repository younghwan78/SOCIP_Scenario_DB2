from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from scenario_db.api.cache import RuleCache

# /health/live + /health/ready — prefix 없이 마운트
health_router = APIRouter(tags=["health"])


@health_router.get("/health/live", summary="Liveness probe")
def liveness():
    """프로세스 생존 여부만 확인. DB 체크 없음."""
    return {"status": "ok"}


@health_router.get("/health/ready", summary="Readiness probe")
def readiness(request: Request):
    """DB 연결 + RuleCache 로드 완료 여부 확인. 503 반환 시 트래픽 차단."""
    cache: RuleCache = request.app.state.rule_cache
    uptime = __import__("time").time() - request.app.state.start_time

    db_ok = False
    try:
        with request.app.state.session_factory() as s:
            s.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    ready = db_ok and cache.loaded
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "version": "0.1.0",
            "uptime_s": round(uptime, 1),
            "db": "connected" if db_ok else "unreachable",
            "rule_cache": {
                "loaded": cache.loaded,
                "issues": len(cache.issues),
                "gate_rules": len(cache.gate_rules),
                "error": cache.load_error,
            },
        },
    )
