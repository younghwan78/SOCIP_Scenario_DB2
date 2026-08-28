from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from scenario_db.api.cache import RuleCache
from scenario_db.config import get_settings


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_rule_cache(
    request: Request,
    db: Session = Depends(get_db),
) -> RuleCache:
    cache: RuleCache = request.app.state.rule_cache
    cache.refresh_if_stale(db, get_settings().rule_cache_ttl_seconds)
    return cache
