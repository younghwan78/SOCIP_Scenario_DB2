"""api/pagination.py — validate_sort_column / apply_sort / PagedResponse 유닛 테스트.

apply_sort의 정상 동작(실제 ORDER BY 생성)은 SQLAlchemy 컬럼 표현식이 필요하므로
integration test에서 검증. 여기서는 에러 경로와 순수 Python 로직만 커버.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from scenario_db.api.pagination import apply_sort, validate_sort_column
from scenario_db.api.schemas.common import PagedResponse


# ---------------------------------------------------------------------------
# 테스트용 fake model — __table__.columns.keys() 지원
# ---------------------------------------------------------------------------

def _fake_model(*cols: str):
    """columns.keys()를 지원하는 최소 ORM 모델 모사."""
    class _Columns:
        @staticmethod
        def keys():
            return list(cols)

    class _Table:
        columns = _Columns()

    class _Model:
        __table__ = _Table()

    for c in cols:
        setattr(_Model, c, MagicMock(name=f"col_{c}"))

    return _Model


# ---------------------------------------------------------------------------
# validate_sort_column
# ---------------------------------------------------------------------------

def test_validate_sort_column_none_returns_none():
    model = _fake_model("id", "name")
    assert validate_sort_column(model, None) is None


def test_validate_sort_column_valid():
    model = _fake_model("id", "name", "category")
    assert validate_sort_column(model, "name") == "name"


def test_validate_sort_column_id_valid():
    model = _fake_model("id", "name")
    assert validate_sort_column(model, "id") == "id"


def test_validate_sort_column_invalid_raises_400():
    model = _fake_model("id", "name")
    with pytest.raises(HTTPException) as exc_info:
        validate_sort_column(model, "nonexistent")
    assert exc_info.value.status_code == 400
    assert "nonexistent" in exc_info.value.detail


def test_validate_sort_column_error_lists_valid_cols():
    model = _fake_model("id", "name")
    with pytest.raises(HTTPException) as exc_info:
        validate_sort_column(model, "bad_col")
    # 에러 메시지에 유효한 컬럼 목록이 포함되어야 함
    assert "id" in exc_info.value.detail or "name" in exc_info.value.detail


# ---------------------------------------------------------------------------
# apply_sort — 에러 경로 (sort_dir 유효성 검사는 SQLAlchemy 호출 전)
# ---------------------------------------------------------------------------

def test_apply_sort_invalid_dir_raises_400():
    q = MagicMock()
    model = _fake_model("id")
    with pytest.raises(HTTPException) as exc_info:
        apply_sort(q, model, None, "INVALID")
    assert exc_info.value.status_code == 400


def test_apply_sort_uppercase_asc_raises_400():
    q = MagicMock()
    model = _fake_model("id")
    with pytest.raises(HTTPException):
        apply_sort(q, model, None, "ASC")


def test_apply_sort_uppercase_desc_raises_400():
    q = MagicMock()
    model = _fake_model("id")
    with pytest.raises(HTTPException):
        apply_sort(q, model, None, "DESC")


# ---------------------------------------------------------------------------
# PagedResponse.from_items
# ---------------------------------------------------------------------------

def test_from_items_basic():
    resp = PagedResponse.from_items(["a", "b"], total=10, limit=2, offset=0)
    assert resp.items == ["a", "b"]
    assert resp.total == 10
    assert resp.limit == 2
    assert resp.offset == 0
    assert resp.has_next is True


def test_from_items_last_page():
    resp = PagedResponse.from_items(["z"], total=5, limit=2, offset=4)
    assert resp.has_next is False


def test_from_items_exact_fit():
    resp = PagedResponse.from_items(["x", "y"], total=2, limit=2, offset=0)
    assert resp.has_next is False


def test_from_items_empty():
    resp = PagedResponse.from_items([], total=0, limit=50, offset=0)
    assert resp.items == []
    assert resp.total == 0
    assert resp.has_next is False


def test_from_items_middle_page():
    resp = PagedResponse.from_items(["c", "d"], total=20, limit=2, offset=6)
    assert resp.has_next is True


# ---------------------------------------------------------------------------
# PagedResponse.from_query — limit clamp
# ---------------------------------------------------------------------------

def _make_query_stub(total: int, items: list):
    q = MagicMock()
    q.count.return_value = total
    q.offset.return_value = q
    q.limit.return_value = q
    q.all.return_value = items
    return q


def test_from_query_clamps_limit_min():
    q = _make_query_stub(5, ["a"])
    resp = PagedResponse.from_query(q, limit=0, offset=0)
    assert resp.limit == 1


def test_from_query_clamps_limit_max():
    q = _make_query_stub(5, ["a"])
    resp = PagedResponse.from_query(q, limit=99999, offset=0, max_limit=1000)
    assert resp.limit == 1000


def test_from_query_has_next_true():
    q = _make_query_stub(total=100, items=list(range(10)))
    resp = PagedResponse.from_query(q, limit=10, offset=0)
    assert resp.has_next is True


def test_from_query_has_next_false():
    q = _make_query_stub(total=5, items=["a", "b", "c", "d", "e"])
    resp = PagedResponse.from_query(q, limit=10, offset=0)
    assert resp.has_next is False
