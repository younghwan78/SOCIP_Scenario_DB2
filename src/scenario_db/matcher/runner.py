from __future__ import annotations

import re
from typing import Any

from scenario_db.matcher.context import MatcherContext

# v2.2 §19 단축 키 → context prefix 매핑
_SHORTHAND_PREFIXES = ("axis", "ip", "sw_feature", "sw_component", "scope")


def evaluate(rule: dict, ctx: MatcherContext) -> bool:
    """
    Issue.affects[*].match_rule JSONB 룰을 평가. True = 이 variant에 영향.

    지원 포맷:
    A) 단축 포맷 (v2.2 §19 fixture):
       {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]}
       {"ip": "ISP.TNR", "field": "mode", "op": "eq", "value": "strong"}
       {"sw_feature": "LLC_dynamic_allocation", "op": "eq", "value": "disabled"}

    B) 도트-경로 포맷 (테스트/API 호출 시):
       {"field": "axis.resolution", "op": "eq", "value": "UHD"}

    Logical combinators:
       {"all": [...]}   AND
       {"any": [...]}   OR
       {"none": [...]}  NOT
    """
    # A rule can combine multiple logical sections at the same level. Treat
    # those sections as AND-ed constraints instead of returning on the first
    # key. This matters for issue rules that combine all/any/none/sw_conditions.
    has_logical = any(k in rule for k in ("all", "any", "none", "sw_conditions", "scope"))
    if has_logical and "op" not in rule:
        if "all" in rule and not all(evaluate(sub, ctx) for sub in rule["all"]):
            return False
        if "any" in rule and not any(evaluate(sub, ctx) for sub in rule["any"]):
            return False
        if "none" in rule and any(evaluate(sub, ctx) for sub in rule["none"]):
            return False
        if "sw_conditions" in rule and not evaluate(rule["sw_conditions"], ctx):
            return False
        # scope is currently an upstream prefilter placeholder.
        return True

    # scope / sw_conditions 키는 상위 컨텍스트 필터 — 현재는 통과 처리
    # (variant context에서 scope 매칭은 별도 로직 필요; Matcher v2에서 구현)
    if "scope" in rule and "op" not in rule:
        return True
    if "sw_conditions" in rule:
        sw_rule = rule["sw_conditions"]
        return evaluate(sw_rule, ctx)

    return _eval_leaf(rule, ctx)


def _resolve_field(rule: dict, ctx: MatcherContext) -> Any:
    """
    단축 포맷과 도트-경로 포맷 모두를 처리해 실제 값을 반환.
    """
    # 도트-경로 포맷: {"field": "axis.resolution", ...}
    if "field" in rule:
        return ctx.get(rule["field"])

    # 단축 포맷: {"axis": "resolution", ...} / {"ip": "ISP.TNR", "field": "mode", ...}
    for prefix in _SHORTHAND_PREFIXES:
        if prefix not in rule:
            continue
        path_val: str = rule[prefix]
        # ip prefix는 선택적 sub-field 추가 지원
        # {"ip": "ISP.TNR", "field": "mode"} → ip.ISP.TNR.mode
        sub = rule.get("field") if prefix == "ip" else None
        dot_path = f"{prefix}.{path_val}" + (f".{sub}" if sub else "")
        return ctx.get(dot_path)

    return None


def _eval_leaf(rule: dict, ctx: MatcherContext) -> bool:
    op: str = rule["op"]
    value: Any = rule.get("value")
    actual: Any = _resolve_field(rule, ctx)

    match op:
        case "eq":
            return actual == value
        case "ne":
            return actual != value
        case "in":
            return actual in value
        case "not_in":
            return actual not in value
        case "gte":
            return actual is not None and actual >= value
        case "lte":
            return actual is not None and actual <= value
        case "gt":
            return actual is not None and actual > value
        case "lt":
            return actual is not None and actual < value
        case "matches":
            return actual is not None and bool(re.search(value, str(actual)))
        case "exists":
            return (actual is not None) is bool(value)
        case "between":
            low, high = value[0], value[1]
            return actual is not None and low <= actual <= high
        case _:
            raise ValueError(
                f"Unknown operator: {op!r}. "
                f"Expected: eq, ne, in, not_in, gte, lte, gt, lt, matches, exists, between"
            )
