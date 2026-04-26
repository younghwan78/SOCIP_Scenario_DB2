"""PostgreSQL JSONB 연산자 — SQLAlchemy 표현식 빌더.

Phase C (Resolver/Gate)에서 SQL-level JSONB 평가를 위한 빌딩 블록.
순수 표현식 생성만 담당 — DB 접속 없음, import side-effect 없음.

지원 연산자:
    @>   containment      feature_flag_contains()
    ->>  text extraction   axis_eq/ne/in/not_in()
    ?    key existence     flag_has_key()
    #>>  nested path       nested_astext()
         jsonb_path_exists() (PG12+)
         match_condition_to_sql() — MatchCondition dict → SQL 표현식
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from sqlalchemy import ColumnElement, and_, func, not_, or_, text
from sqlalchemy.dialects.postgresql import JSONB


# ---------------------------------------------------------------------------
# 1. axis 조건 → design_conditions JSONB
# ---------------------------------------------------------------------------

def axis_eq(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    """design_conditions->>'axis' = value"""
    return col[axis].astext == str(value)


def axis_ne(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    return col[axis].astext != str(value)


def axis_in(col: ColumnElement, axis: str, values: Sequence) -> ColumnElement:
    """design_conditions->>'axis' = ANY(ARRAY[...])"""
    return col[axis].astext.in_([str(v) for v in values])


def axis_not_in(col: ColumnElement, axis: str, values: Sequence) -> ColumnElement:
    return col[axis].astext.not_in([str(v) for v in values])


def axis_gt(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    """수치 비교 — ::numeric 캐스트."""
    return col[axis].astext.cast(JSONB).cast("numeric") > value


def axis_gte(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    return col[axis].astext.cast(JSONB).cast("numeric") >= value


def axis_lt(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    return col[axis].astext.cast(JSONB).cast("numeric") < value


def axis_lte(col: ColumnElement, axis: str, value: Any) -> ColumnElement:
    return col[axis].astext.cast(JSONB).cast("numeric") <= value


def axis_matches(col: ColumnElement, axis: str, pattern: str) -> ColumnElement:
    """design_conditions->>'axis' ~ 'pattern' (PostgreSQL regex)."""
    return col[axis].astext.regexp_match(pattern)


def axis_exists(col: ColumnElement, axis: str, expected: bool = True) -> ColumnElement:
    """키 존재 여부 — ? 연산자."""
    if expected:
        return col.has_key(axis)
    return not_(col.has_key(axis))


# ---------------------------------------------------------------------------
# 2. feature_flags JSONB → @> / ? 연산자
# ---------------------------------------------------------------------------

def flag_contains(col: ColumnElement, name: str, value: str) -> ColumnElement:
    """feature_flags @> '{"name": "value"}'::jsonb — GIN 인덱스 활용."""
    return col.contains({name: value})


def flag_has_key(col: ColumnElement, key: str) -> ColumnElement:
    """feature_flags ? 'key' — 키 존재 확인."""
    return col.has_key(key)


def flag_multi_contains(col: ColumnElement, flags: dict[str, str]) -> ColumnElement:
    """feature_flags @> '{k1: v1, k2: v2}'::jsonb — 다중 플래그 동시 검사."""
    return col.contains(flags)


# ---------------------------------------------------------------------------
# 3. 중첩 JSONB 경로
# ---------------------------------------------------------------------------

def nested_astext(col: ColumnElement, *keys: str) -> ColumnElement:
    """col #>> '{k1, k2, ...}' — 중첩 경로 텍스트 추출.

    예) nested_astext(ip_requirements, "isp0", "required_bitdepth")
        → ip_requirements #>> '{isp0,required_bitdepth}'
    """
    expr: ColumnElement = col
    for k in keys:
        expr = expr[k]
    return expr.astext


def ip_condition_eq(col: ColumnElement, ip_key: str, field: str, value: Any) -> ColumnElement:
    """ip_requirements #>> '{ip_key, field}' = value."""
    return nested_astext(col, ip_key, field) == str(value)


def ip_condition_in(col: ColumnElement, ip_key: str, field: str, values: Sequence) -> ColumnElement:
    return nested_astext(col, ip_key, field).in_([str(v) for v in values])


# ---------------------------------------------------------------------------
# 4. jsonb_path_exists() — PG12+
# ---------------------------------------------------------------------------

def jsonb_path_exists(col: ColumnElement, jsonpath: str) -> ColumnElement:
    """jsonb_path_exists(col, jsonpath::jsonpath) — JSONPath 존재 확인.

    예) jsonb_path_exists(design_conditions, '$.resolution ? (@ == "UHD")')
    """
    return func.jsonb_path_exists(col, text(f"'{jsonpath}'::jsonpath"))


def jsonb_path_query_first(col: ColumnElement, jsonpath: str) -> ColumnElement:
    """jsonb_path_query_first(col, path) — JSONPath 첫 번째 값 추출."""
    return func.jsonb_path_query_first(col, text(f"'{jsonpath}'::jsonpath"))


# ---------------------------------------------------------------------------
# 5. MatchCondition dict → SQLAlchemy 표현식 (부분 번역)
# ---------------------------------------------------------------------------

# SQL 번역 가능한 prefix
_SQL_TRANSLATABLE_PREFIXES = {"axis", "ip"}

# SQL 번역 가능한 연산자
_SQL_OPS = {"eq", "ne", "in", "not_in", "gt", "gte", "lt", "lte", "matches", "exists"}


def match_condition_to_sql(
    condition: dict,
    design_cond_col: ColumnElement,
    ip_req_col: ColumnElement | None = None,
) -> ColumnElement | None:
    """MatchCondition dict → SQLAlchemy WHERE 절.

    번역 가능:
    - axis.* → design_conditions JSONB (->> 계열)
    - ip.* (단순 필드) → ip_requirements JSONB (#>> 계열)

    번역 불가 (None 반환 → Python fallback):
    - sw_feature.* (sw_profile JOIN 필요)
    - sw_component.* (sw_profile JOIN 필요)
    - scope.* (execution_context, variant에 없음)
    """
    op = condition.get("op")
    value = condition.get("value")

    if op not in _SQL_OPS:
        return None  # Python fallback

    # --- axis 조건 ---
    if "axis" in condition:
        axis = condition["axis"]
        col = design_cond_col
        match op:
            case "eq":      return axis_eq(col, axis, value)
            case "ne":      return axis_ne(col, axis, value)
            case "in":      return axis_in(col, axis, value)
            case "not_in":  return axis_not_in(col, axis, value)
            case "gt":      return axis_gt(col, axis, value)
            case "gte":     return axis_gte(col, axis, value)
            case "lt":      return axis_lt(col, axis, value)
            case "lte":     return axis_lte(col, axis, value)
            case "matches": return axis_matches(col, axis, str(value))
            case "exists":  return axis_exists(col, axis, bool(value))
        return None

    # --- ip 조건 (단순: ip_key + field 2레벨만) ---
    if "ip" in condition and ip_req_col is not None:
        ip_path = condition["ip"]     # e.g. "ISP.TNR" → key1="ISP", key2="TNR"
        field = condition.get("field")  # e.g. "mode"
        if not field:
            return None  # field 없으면 번역 불가
        # ip_path를 점 구분으로 split (최대 2레벨)
        parts = ip_path.split(".", 1)
        ip_key = parts[0]
        sub_key = parts[1] if len(parts) > 1 else None
        keys = [ip_key] + ([sub_key] if sub_key else []) + [field]
        expr = nested_astext(ip_req_col, *keys)
        match op:
            case "eq":      return expr == str(value)
            case "ne":      return expr != str(value)
            case "in":      return expr.in_([str(v) for v in value])
            case "not_in":  return expr.not_in([str(v) for v in value])
        return None

    # sw_feature / sw_component / scope → Python fallback
    return None


def match_rule_all_to_sql(
    rule: dict,
    design_cond_col: ColumnElement,
    ip_req_col: ColumnElement | None = None,
) -> ColumnElement | None:
    """match_rule.all 조건 목록 → SQL AND 표현식 (번역 가능한 것만).

    번역 불가 조건은 건너뜀 — Python에서 재평가 필요.
    모든 조건이 번역 불가이면 None 반환.
    """
    conditions = rule.get("all", [])
    sql_parts = []
    for cond in conditions:
        expr = match_condition_to_sql(cond, design_cond_col, ip_req_col)
        if expr is not None:
            sql_parts.append(expr)
    if not sql_parts:
        return None
    if len(sql_parts) == 1:
        return sql_parts[0]
    return and_(*sql_parts)
