from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from scenario_db.models.decision.common import (
    Attestation,
    AuthMethod,
    GateResultStatus,
    MatchCondition,
    MatchOp,
    MatchRule,
    MatchScope,
    SwConditions,
)
from scenario_db.models.decision.gate_rule import (
    GateCondition,
    GateRule,
)
from scenario_db.models.decision.issue import (
    Issue,
    IssueStatus,
    SwRegression,
)
from scenario_db.models.decision.review import (
    AutoCheck,
    Review,
    ReviewDecision,
    WaiverStatus,
)
from scenario_db.models.decision.waiver import Waiver

FIXTURES = Path(__file__).parent / "fixtures" / "decision"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def roundtrip(model_cls, path: Path, **dump_kwargs):
    raw = load_yaml(path)
    obj = model_cls.model_validate(raw)
    serialised = obj.model_dump(exclude_none=True, **dump_kwargs)
    obj2 = model_cls.model_validate(serialised)
    assert obj == obj2
    return obj


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_review_roundtrip():
    obj = roundtrip(Review, FIXTURES / "rev-camera-recording-UHD60-A0-20260417.yaml")
    assert obj.kind == "decision.review"
    assert obj.gate_result == GateResultStatus.WARN
    assert obj.decision == ReviewDecision.approved_with_waiver


def test_waiver_roundtrip():
    obj = roundtrip(Waiver, FIXTURES / "waiver-LLC-thrashing-UHD60-A0-20260417.yaml")
    assert obj.kind == "decision.waiver"
    assert obj.status == WaiverStatus.pending_auth


def test_issue_roundtrip():
    obj = roundtrip(Issue, FIXTURES / "iss-LLC-thrashing-0221.yaml")
    assert obj.kind == "decision.issue"
    assert obj.metadata.status == IssueStatus.resolved


def test_gate_rule_roundtrip():
    obj = roundtrip(GateRule, FIXTURES / "rule-feasibility-check.yaml")
    assert obj.kind == "decision.gate_rule"
    assert obj.action.gate_result == GateResultStatus.BLOCK


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

def test_attestation_server_null():
    att = Attestation.model_validate({
        "approver_claim": "YHJOO",
        "claim_at": "2026-04-17",
        "server_attestation": {
            "approved_by_auth": None,
            "auth_method": None,
            "auth_timestamp": None,
            "auth_session_id": None,
        },
    })
    assert att.server_attestation.approved_by_auth is None
    assert att.server_attestation.auth_method is None


def test_attestation_server_filled():
    att = Attestation.model_validate({
        "approver_claim": "LeeSR",
        "claim_at": "2026-04-17",
        "git_attestation": {
            "commit_sha": "def5678",
            "commit_author_email": "leesr@company.internal",
            "signed": True,
        },
        "server_attestation": {
            "approved_by_auth": "sub|leesr@sso",
            "auth_method": "sso",
            "auth_timestamp": "2026-04-18T10:00:00Z",
            "auth_session_id": "sess-abc123",
        },
    })
    assert att.server_attestation.approved_by_auth == "sub|leesr@sso"
    assert att.server_attestation.auth_method == AuthMethod.sso
    assert att.git_attestation.signed is True


def test_auth_method_enum():
    assert set(AuthMethod) == {"sso", "mfa", "signed_jwt"}


# ---------------------------------------------------------------------------
# MatchOp — Python reserved word 'in'
# ---------------------------------------------------------------------------

def test_match_op_in_keyword():
    cond = MatchCondition.model_validate({
        "axis": "resolution",
        "op": "in",
        "value": ["UHD", "8K"],
    })
    assert cond.op == MatchOp.in_
    assert cond.op == "in"           # StrEnum: value comparison works


# ---------------------------------------------------------------------------
# MatchCondition subject fields
# ---------------------------------------------------------------------------

def test_match_condition_axis():
    cond = MatchCondition.model_validate({
        "axis": "thermal", "op": "eq", "value": "hot"
    })
    assert cond.axis == "thermal"
    assert cond.sw_feature is None


def test_match_condition_sw_feature():
    cond = MatchCondition.model_validate({
        "sw_feature": "LLC_dynamic_allocation", "op": "eq", "value": "disabled"
    })
    assert cond.sw_feature == "LLC_dynamic_allocation"


def test_match_condition_sw_component():
    cond = MatchCondition.model_validate({
        "sw_component": "kernel.drivers.camera",
        "op": "matches",
        "value": "exynos-cam-v[12]\\..*",
    })
    assert cond.sw_component == "kernel.drivers.camera"


def test_match_condition_single_subject():
    """axis + ip 동시 입력 → ValidationError (상호 배타성)."""
    with pytest.raises(ValidationError, match="exactly one subject"):
        MatchCondition.model_validate({
            "axis": "resolution",
            "ip": "ISP.TNR",
            "op": "eq",
            "value": "UHD",
        })


def test_match_condition_no_subject():
    """subject 없으면 ValidationError."""
    with pytest.raises(ValidationError, match="exactly one subject"):
        MatchCondition.model_validate({"op": "eq", "value": "hot"})


def test_match_condition_op_value_compat():
    """`op: between` + 스칼라 값 → ValidationError."""
    with pytest.raises(ValidationError, match="between"):
        MatchCondition.model_validate({
            "axis": "fps", "op": "between", "value": 60
        })


def test_match_condition_op_in_requires_list():
    """`op: in` + 스칼라 값 → ValidationError."""
    with pytest.raises(ValidationError):
        MatchCondition.model_validate({
            "axis": "thermal", "op": "in", "value": "hot"
        })


# ---------------------------------------------------------------------------
# MatchRule structures
# ---------------------------------------------------------------------------

def test_match_rule_all_any_none():
    rule = MatchRule.model_validate({
        "all": [{"axis": "resolution", "op": "eq", "value": "UHD"}],
        "any": [{"axis": "fps", "op": "gte", "value": 60}],
        "none": [{"axis": "power_state", "op": "eq", "value": "battery"}],
    })
    assert len(rule.all) == 1
    assert len(rule.any) == 1
    assert len(rule.none) == 1


def test_match_rule_sw_conditions():
    rule = MatchRule.model_validate({
        "all": [{"axis": "thermal", "op": "in", "value": ["hot", "critical"]}],
        "sw_conditions": {
            "any": [
                {"sw_feature": "LLC_dynamic_allocation", "op": "eq", "value": "disabled"},
                {"sw_component": "kernel.drivers.camera", "op": "matches", "value": "exynos-cam-v.*"},
            ]
        },
    })
    assert rule.sw_conditions is not None
    assert len(rule.sw_conditions.any) == 2


def test_match_scope_wildcard():
    """`project_ref: "*"` — DocumentId 아닌 str 허용."""
    scope = MatchScope.model_validate({
        "project_ref": "*",
        "soc_ref": "soc-exynos2500",
    })
    assert scope.project_ref == "*"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

def test_waiver_status_enum():
    assert set(WaiverStatus) == {"pending_auth", "approved", "revoked", "expired"}


def test_issue_status_enum():
    assert set(IssueStatus) == {"open", "resolved", "wontfix", "deferred"}


def test_gate_result_status_enum():
    assert set(GateResultStatus) == {"PASS", "WARN", "BLOCK"}


# ---------------------------------------------------------------------------
# Issue internals
# ---------------------------------------------------------------------------

def test_issue_sw_regression():
    obj = roundtrip(Issue, FIXTURES / "iss-LLC-thrashing-0221.yaml")
    reg = obj.metadata.sw_regression
    assert reg.discovered_in_sw == "sw-vendor-v1.2.1"
    assert reg.last_good_sw == "sw-vendor-v1.2.0"
    assert reg.root_cause_sw_change.area == "camera.llc_policy"
    assert reg.fixed_in_sw == "sw-vendor-v1.3.0"


def test_issue_pmu_signature():
    obj = roundtrip(Issue, FIXTURES / "iss-LLC-thrashing-0221.yaml")
    sigs = {s.counter: s.threshold for s in obj.pmu_signature}
    assert sigs["STALL_BACKEND_MEM"] == ">40%"
    assert sigs["L2D_CACHE_REFILL"] == ">1M/s"


# ---------------------------------------------------------------------------
# Review — AutoCheck FK
# ---------------------------------------------------------------------------

def test_auto_check_with_matched_issues():
    obj = roundtrip(Review, FIXTURES / "rev-camera-recording-UHD60-A0-20260417.yaml")
    known_issue_check = next(
        c for c in obj.auto_checks if c.matched_issues
    )
    assert "iss-LLC-thrashing-0221" in known_issue_check.matched_issues


def test_review_waiver_ref_document_id():
    obj = roundtrip(Review, FIXTURES / "rev-camera-recording-UHD60-A0-20260417.yaml")
    assert obj.waiver_ref == "waiver-LLC-thrashing-UHD60-A0-20260417"
    # waiver- prefix는 DocumentId 패턴에 포함
    with pytest.raises(ValidationError):
        AutoCheck.model_validate({
            "rule_ref": "invalid-prefix-rule",  # "invalid" 접두사는 DocumentId 불가
            "status": "PASS",
        })


# ---------------------------------------------------------------------------
# GateRule — Sugar DSL dict
# ---------------------------------------------------------------------------

def test_gate_rule_sugar_condition():
    """condition.match는 중첩 dict(Sugar DSL) 허용 — 내부 구조 비검증."""
    obj = roundtrip(GateRule, FIXTURES / "rule-feasibility-check.yaml")
    match = obj.condition.match
    assert match is not None
    # Sugar 값이 dict로 저장됨
    key = "evidence.resolution_result.overall_feasibility"
    assert key in match
    assert isinstance(match[key], dict)


def test_gate_condition_sugar_dict_typing():
    """condition.match에 복잡한 중첩 dict 파싱 및 dump."""
    cond = GateCondition.model_validate({
        "match": {
            "evidence.resolution_result.sw_resolution.required_features_check": {
                "$any_item": {"status": "FAIL"}
            }
        }
    })
    dumped = cond.model_dump(exclude_none=True)
    assert "$any_item" in str(dumped)


# ---------------------------------------------------------------------------
# Extra fields forbidden
# ---------------------------------------------------------------------------

def test_extra_fields_forbidden_review():
    raw = load_yaml(FIXTURES / "rev-camera-recording-UHD60-A0-20260417.yaml")
    raw["unknown_field"] = "oops"
    with pytest.raises(ValidationError):
        Review.model_validate(raw)


def test_extra_fields_forbidden_waiver():
    raw = load_yaml(FIXTURES / "waiver-LLC-thrashing-UHD60-A0-20260417.yaml")
    raw["ghost"] = True
    with pytest.raises(ValidationError):
        Waiver.model_validate(raw)
