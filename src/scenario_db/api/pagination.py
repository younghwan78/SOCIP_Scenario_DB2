"""Pagination + sort 유틸리티.

모든 list 엔드포인트에서 import해서 사용.
sort_by 검증 정책은 한 가지다: 모델 컬럼에 없으면 400 (silent fallback 없음).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import asc, desc
from sqlalchemy.orm import Query

from scenario_db.exceptions import BadRequestError

_SORT_DIRS = {"asc": asc, "desc": desc}


def apply_sort(
    query: Query,
    model: Any,
    sort_by: str | None,
    sort_dir: str = "asc",
    default_col: str = "id",
) -> Query:
    """ORM query에 ORDER BY 적용.

    sort_by가 None이면 default_col 사용. 모델 컬럼에 없으면 400 —
    validate_sort_column과 같은 정책이라 라우터/레포지토리 어느 경로로
    들어와도 같은 입력은 같은 결과를 낸다 (review 5.4).
    sort_dir이 "asc"/"desc" 외이면 400.
    """
    if sort_dir not in _SORT_DIRS:
        raise BadRequestError("sort_dir must be 'asc' or 'desc'")

    col_name = validate_sort_column(model, sort_by) or default_col
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
        raise BadRequestError(
            f"sort_by '{sort_by}' is not a valid column. Valid: {sorted(cols)}"
        )
    return sort_by
