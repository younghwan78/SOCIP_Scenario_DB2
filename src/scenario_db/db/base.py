from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None, **kwargs) -> Engine:
    db_url = url or os.environ["DATABASE_URL"]
    return create_engine(db_url, **kwargs)
