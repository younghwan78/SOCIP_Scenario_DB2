from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from scenario_db.config import get_settings


class Base(DeclarativeBase):
    pass


def resolve_database_url(url: str | None = None) -> str:
    """Resolve the DB URL through the same precedence used by app settings."""
    if url:
        return url
    try:
        return get_settings().database_url
    except Exception:
        # Preserve the historic KeyError shape for low-level callers that only
        # configured DATABASE_URL and do not instantiate Settings directly.
        return os.environ["DATABASE_URL"]


def make_engine(url: str | None = None, **kwargs) -> Engine:
    return create_engine(resolve_database_url(url), **kwargs)
