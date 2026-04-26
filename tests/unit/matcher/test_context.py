"""MatcherContext 단위 테스트 — factory methods + get() 경로 파싱."""

import pytest

from scenario_db.matcher.context import MatcherContext


# ---------------------------------------------------------------------------
# MatcherContext.get() — 경로 파싱
# ---------------------------------------------------------------------------

@pytest.fixture
def full_ctx() -> MatcherContext:
    return MatcherContext(
        design_conditions={"resolution": "FHD", "fps": 30, "hdr": None},
        ip_requirements={"ISP": {"TNR": {"strength": 2, "mode": "spatial"}, "count": 2}},
        sw_requirements={
            "feature_flags": {"LLC_per_ip_partition": "enabled", "MFC_hwae": "disabled"},
            "components": {"kernel": "5.15.0", "hal": "v3.0.0"},
        },
        execution_context={"phase": "post-si", "tool": "simtop"},
    )


def test_get_axis_simple(full_ctx):
    assert full_ctx.get("axis.resolution") == "FHD"
    assert full_ctx.get("axis.fps") == 30


def test_get_axis_null_value(full_ctx):
    assert full_ctx.get("axis.hdr") is None


def test_get_axis_missing(full_ctx):
    assert full_ctx.get("axis.nonexistent") is None


def test_get_ip_nested_two_levels(full_ctx):
    assert full_ctx.get("ip.ISP.count") == 2


def test_get_ip_nested_three_levels(full_ctx):
    assert full_ctx.get("ip.ISP.TNR.strength") == 2
    assert full_ctx.get("ip.ISP.TNR.mode") == "spatial"


def test_get_ip_missing_subtree(full_ctx):
    assert full_ctx.get("ip.MFC.count") is None


def test_get_sw_feature(full_ctx):
    assert full_ctx.get("sw_feature.LLC_per_ip_partition") == "enabled"
    assert full_ctx.get("sw_feature.MFC_hwae") == "disabled"


def test_get_sw_feature_missing(full_ctx):
    assert full_ctx.get("sw_feature.nonexistent") is None


def test_get_sw_component(full_ctx):
    assert full_ctx.get("sw_component.kernel") == "5.15.0"
    assert full_ctx.get("sw_component.hal") == "v3.0.0"


def test_get_scope(full_ctx):
    assert full_ctx.get("scope.phase") == "post-si"
    assert full_ctx.get("scope.tool") == "simtop"


def test_get_unknown_prefix(full_ctx):
    with pytest.raises(KeyError, match="Unknown context prefix"):
        full_ctx.get("bad.field")


# ---------------------------------------------------------------------------
# Empty context fallback
# ---------------------------------------------------------------------------

def test_empty_context_all_none():
    ctx = MatcherContext()
    assert ctx.get("axis.resolution") is None
    assert ctx.get("ip.ISP.count") is None
    assert ctx.get("sw_feature.LLC_per_ip_partition") is None
    assert ctx.get("scope.phase") is None


# ---------------------------------------------------------------------------
# from_variant() factory
# ---------------------------------------------------------------------------

class _FakeVariant:
    design_conditions = {"resolution": "UHD", "fps": 60}
    ip_requirements = {"ISP": {"count": 1}}
    sw_requirements = {"feature_flags": {"LLC_per_ip_partition": "disabled"}}


def test_from_variant():
    ctx = MatcherContext.from_variant(_FakeVariant())
    assert ctx.get("axis.resolution") == "UHD"
    assert ctx.get("ip.ISP.count") == 1
    assert ctx.get("sw_feature.LLC_per_ip_partition") == "disabled"
    assert ctx.get("scope.phase") is None  # execution_context not set


# ---------------------------------------------------------------------------
# from_evidence() factory
# ---------------------------------------------------------------------------

class _FakeEvidence:
    execution_context = {"phase": "pre-si", "sw_baseline_ref": "sw-vendor-v1.3.0"}
    variant = _FakeVariant()


def test_from_evidence():
    ctx = MatcherContext.from_evidence(_FakeEvidence())
    assert ctx.get("axis.resolution") == "UHD"
    assert ctx.get("scope.phase") == "pre-si"
    assert ctx.get("scope.sw_baseline_ref") == "sw-vendor-v1.3.0"


def test_from_evidence_no_variant():
    class _EvidenceNoVariant:
        execution_context = {"phase": "pre-si"}
        variant = None

    ctx = MatcherContext.from_evidence(_EvidenceNoVariant())
    assert ctx.get("axis.resolution") is None
    assert ctx.get("scope.phase") == "pre-si"
