"""
matcher/runner.py 단위 테스트.

커버리지:
  - 11개 operator (eq, ne, in, not_in, gte, lte, gt, lt, matches, exists, between)
  - 3개 logical combinator (all, any, none) + 중첩
  - 5개 field accessor prefix (axis, ip, sw_feature, sw_component, scope)
  - 실 fixture: iss-LLC-thrashing-0221 affects 룰 + UHD60-HDR10-H265 variant 통합
"""

import pytest

from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate


# ---------------------------------------------------------------------------
# Shared context fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def ctx() -> MatcherContext:
    return MatcherContext(
        design_conditions={
            "resolution": "UHD",
            "fps": 60,
            "hdr": "HDR10",
            "codec": "H265",
        },
        ip_requirements={
            "ISP": {"TNR": {"strength": 3}, "count": 1},
        },
        sw_requirements={
            "feature_flags": {
                "LLC_per_ip_partition": "enabled",
                "LLC_dynamic_allocation": "disabled",
                "TNR_early_abort": "disabled",
                "MFC_hwae": "enabled",
            },
            "components": {
                "kernel": "5.10.198",
                "hal": "v2.1.0",
            },
        },
        execution_context={
            "phase": "pre-si",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
        },
    )


# ---------------------------------------------------------------------------
# Operator tests
# ---------------------------------------------------------------------------

def test_op_eq_match(ctx):
    assert evaluate({"field": "axis.resolution", "op": "eq", "value": "UHD"}, ctx) is True


def test_op_eq_no_match(ctx):
    assert evaluate({"field": "axis.resolution", "op": "eq", "value": "FHD"}, ctx) is False


def test_op_ne(ctx):
    assert evaluate({"field": "axis.fps", "op": "ne", "value": 30}, ctx) is True


def test_op_in(ctx):
    assert evaluate({"field": "axis.codec", "op": "in", "value": ["H264", "H265", "AV1"]}, ctx) is True


def test_op_not_in(ctx):
    assert evaluate({"field": "axis.codec", "op": "not_in", "value": ["H264", "AV1"]}, ctx) is True


def test_op_gte(ctx):
    assert evaluate({"field": "axis.fps", "op": "gte", "value": 60}, ctx) is True
    assert evaluate({"field": "axis.fps", "op": "gte", "value": 61}, ctx) is False


def test_op_lte(ctx):
    assert evaluate({"field": "axis.fps", "op": "lte", "value": 60}, ctx) is True
    assert evaluate({"field": "axis.fps", "op": "lte", "value": 59}, ctx) is False


def test_op_gt(ctx):
    assert evaluate({"field": "axis.fps", "op": "gt", "value": 59}, ctx) is True
    assert evaluate({"field": "axis.fps", "op": "gt", "value": 60}, ctx) is False


def test_op_lt(ctx):
    assert evaluate({"field": "axis.fps", "op": "lt", "value": 61}, ctx) is True
    assert evaluate({"field": "axis.fps", "op": "lt", "value": 60}, ctx) is False


def test_op_matches(ctx):
    assert evaluate({"field": "axis.hdr", "op": "matches", "value": r"^HDR"}, ctx) is True
    assert evaluate({"field": "axis.hdr", "op": "matches", "value": r"^SDR"}, ctx) is False


def test_op_exists_true(ctx):
    assert evaluate({"field": "axis.resolution", "op": "exists", "value": True}, ctx) is True
    assert evaluate({"field": "axis.nonexistent", "op": "exists", "value": True}, ctx) is False


def test_op_exists_false(ctx):
    assert evaluate({"field": "axis.nonexistent", "op": "exists", "value": False}, ctx) is True
    assert evaluate({"field": "axis.resolution", "op": "exists", "value": False}, ctx) is False


def test_op_between(ctx):
    assert evaluate({"field": "axis.fps", "op": "between", "value": [30, 120]}, ctx) is True
    assert evaluate({"field": "axis.fps", "op": "between", "value": [61, 120]}, ctx) is False


def test_op_unknown_raises(ctx):
    with pytest.raises(ValueError, match="Unknown operator"):
        evaluate({"field": "axis.fps", "op": "xor", "value": 60}, ctx)


def test_mixed_logical_sections_are_combined_as_and(ctx):
    rule = {
        "all": [
            {"field": "axis.resolution", "op": "eq", "value": "UHD"},
        ],
        "any": [
            {"field": "sw_feature.LLC_dynamic_allocation", "op": "eq", "value": "disabled"},
            {"field": "sw_feature.LLC_per_ip_partition", "op": "eq", "value": "disabled"},
        ],
        "none": [
            {"field": "scope.phase", "op": "eq", "value": "post-si"},
        ],
    }

    assert evaluate(rule, ctx) is True


def test_mixed_logical_sections_fail_when_any_section_fails(ctx):
    rule = {
        "all": [
            {"field": "axis.resolution", "op": "eq", "value": "UHD"},
        ],
        "any": [
            {"field": "sw_feature.LLC_dynamic_allocation", "op": "eq", "value": "enabled"},
        ],
        "none": [
            {"field": "scope.phase", "op": "eq", "value": "post-si"},
        ],
    }

    assert evaluate(rule, ctx) is False


# ---------------------------------------------------------------------------
# Logical combinator tests
# ---------------------------------------------------------------------------

def test_all_match(ctx):
    rule = {"all": [
        {"field": "axis.resolution", "op": "eq", "value": "UHD"},
        {"field": "axis.fps", "op": "gte", "value": 60},
    ]}
    assert evaluate(rule, ctx) is True


def test_all_partial_fail(ctx):
    rule = {"all": [
        {"field": "axis.resolution", "op": "eq", "value": "UHD"},
        {"field": "axis.fps", "op": "gt", "value": 60},   # fails
    ]}
    assert evaluate(rule, ctx) is False


def test_any_one_match(ctx):
    rule = {"any": [
        {"field": "axis.resolution", "op": "eq", "value": "FHD"},  # fails
        {"field": "axis.fps", "op": "eq", "value": 60},            # passes
    ]}
    assert evaluate(rule, ctx) is True


def test_any_none_match(ctx):
    rule = {"any": [
        {"field": "axis.resolution", "op": "eq", "value": "FHD"},
        {"field": "axis.fps", "op": "eq", "value": 30},
    ]}
    assert evaluate(rule, ctx) is False


def test_none_combinator(ctx):
    rule = {"none": [
        {"field": "axis.resolution", "op": "eq", "value": "FHD"},
        {"field": "axis.fps", "op": "eq", "value": 30},
    ]}
    assert evaluate(rule, ctx) is True  # none of them match → True


def test_none_combinator_has_match(ctx):
    rule = {"none": [
        {"field": "axis.resolution", "op": "eq", "value": "UHD"},  # matches
    ]}
    assert evaluate(rule, ctx) is False


def test_nested_all_any(ctx):
    rule = {"all": [
        {"field": "axis.resolution", "op": "eq", "value": "UHD"},
        {"any": [
            {"field": "axis.fps", "op": "eq", "value": 30},
            {"field": "axis.fps", "op": "eq", "value": 60},
        ]},
    ]}
    assert evaluate(rule, ctx) is True


# ---------------------------------------------------------------------------
# Field accessor prefix tests
# ---------------------------------------------------------------------------

def test_accessor_axis(ctx):
    assert ctx.get("axis.resolution") == "UHD"


def test_accessor_ip_nested(ctx):
    assert ctx.get("ip.ISP.TNR.strength") == 3
    assert ctx.get("ip.ISP.count") == 1


def test_accessor_sw_feature(ctx):
    assert ctx.get("sw_feature.LLC_per_ip_partition") == "enabled"
    assert ctx.get("sw_feature.TNR_early_abort") == "disabled"


def test_accessor_sw_component(ctx):
    assert ctx.get("sw_component.kernel") == "5.10.198"


def test_accessor_scope(ctx):
    assert ctx.get("scope.phase") == "pre-si"
    assert ctx.get("scope.sw_baseline_ref") == "sw-vendor-v1.2.3"


def test_accessor_unknown_prefix_raises(ctx):
    with pytest.raises(KeyError, match="Unknown context prefix"):
        ctx.get("unknown.field")


def test_accessor_missing_field_returns_none(ctx):
    assert ctx.get("axis.nonexistent") is None


# ---------------------------------------------------------------------------
# Integration test: iss-LLC-thrashing-0221 × UHD60-HDR10-H265 variant
# ---------------------------------------------------------------------------

LLC_THRASHING_AFFECTS = {
    "all": [
        {"field": "axis.resolution", "op": "in", "value": ["UHD", "4K"]},
        {"field": "axis.fps", "op": "gte", "value": 60},
        {"field": "sw_feature.LLC_per_ip_partition", "op": "eq", "value": "disabled"},
    ]
}

def test_llc_thrashing_no_match_v123(ctx):
    """v1.2.3: LLC_per_ip_partition=enabled → issue does NOT affect (condition requires disabled)."""
    # The fixture has LLC_per_ip_partition=enabled, so the "disabled" condition fails
    assert evaluate(LLC_THRASHING_AFFECTS, ctx) is False


def test_llc_thrashing_matches_when_disabled():
    """Simulate v1.2.3 variant where LLC partition is disabled → issue affects."""
    ctx_v123 = MatcherContext(
        design_conditions={"resolution": "UHD", "fps": 60},
        sw_requirements={"feature_flags": {"LLC_per_ip_partition": "disabled"}},
    )
    assert evaluate(LLC_THRASHING_AFFECTS, ctx_v123) is True


def test_llc_thrashing_no_match_low_fps():
    """Low fps variant is not affected even with LLC disabled."""
    ctx_low = MatcherContext(
        design_conditions={"resolution": "UHD", "fps": 30},
        sw_requirements={"feature_flags": {"LLC_per_ip_partition": "disabled"}},
    )
    assert evaluate(LLC_THRASHING_AFFECTS, ctx_low) is False
