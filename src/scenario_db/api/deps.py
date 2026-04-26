from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from scenario_db.api.cache import RuleCache


def get_db(request: Request):
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_rule_cache(request: Request) -> RuleCache:
    return request.app.state.rule_cache
