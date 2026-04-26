"""Pagination + sort 유틸리티.

모든 list 엔드포인트에서 import해서 사용.
sort_by는 호출 측에서 whitelist 검증 후 전달 (invalid 컬럼은 None 처리).
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Query

_SORT_DIRS = {"asc": asc, "desc": desc}


def apply_sort(
    query: Query,
    model: Any,
    sort_by: str | None,
    sort_dir: str = "asc",
    default_col: str = "id",
) -> Query:
    """ORM query에 ORDER BY 적용.

    sort_by가 None이거나 모델 컬럼에 없으면 default_col 사용.
    sort_dir이 "asc"/"desc" 외이면 400.
    """
    if sort_dir not in _SORT_DIRS:
        raise HTTPException(status_code=400, detail="sort_dir must be 'asc' or 'desc'")

    col_name = sort_by or default_col
    col = getattr(model, col_name, None)
    if col is None:
        col = getattr(model, default_col)

    direction = _SORT_DIRS[sort_dir]
    return query.order_by(direction(col))


def validate_sort_column(model: Any, sort_by: str | None) -> str | None:
    """sort_by 컬럼명이 모델에 존재하는지 확인. 없으면 400."""
    if sort_by is None:
        return None
    cols = set(model.__table__.columns.keys())
    if sort_by not in cols:
        raise HTTPException(
            status_code=400,
            detail=f"sort_by '{sort_by}' is not a valid column. Valid: {sorted(cols)}",
        )
    return sort_by
