"""RuleCache 실 PostgreSQL 검증."""
import pytest
from sqlalchemy.orm import Session

from scenario_db.api.cache import RuleCache, match_issues_for_variant
from scenario_db.api.schemas.decision import IssueResponse
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.matcher.context import MatcherContext

pytestmark = pytest.mark.integration


def test_rulecache_load_succeeds(rule_cache: RuleCache):
    assert rule_cache.loaded is True
    assert rule_cache.load_error is None
    assert len(rule_cache.issues) >= 1
    assert len(rule_cache.gate_rules) >= 1


def test_rulecache_issues_have_affects(rule_cache: RuleCache):
    for iss in rule_cache.issues:
        if iss.affects is not None:
            assert isinstance(iss.affects, list), f"affects must be list, got {type(iss.affects)}"


def test_rulecache_gate_rules_have_ids(rule_cache: RuleCache):
    for gr in rule_cache.gate_rules:
        assert gr.id is not None and gr.id != ""


def test_match_issues_for_variant_uhd60_no_thermal(engine):
    """UHD60-HDR10-H265 variant — thermal 컨텍스트 없이는 LLC thrashing issue가 매칭되지 않아야 함.

    iss-LLC-thrashing-0221 match_rule.all 조건:
      - axis.resolution in [UHD, 8K]  → UHD → True
      - axis.thermal in [hot, critical] → None (variant에 없음) → False
    all 조건이 False → 이슈 미매칭이 올바른 동작.
    """
    with Session(engine) as session:
        cache = RuleCache.load(session)
        variant = (
            session.query(ScenarioVariant)
            .filter_by(scenario_id="uc-camera-recording", id="UHD60-HDR10-H265")
            .one_or_none()
        )
    assert variant is not None, "UHD60-HDR10-H265 variant가 DB에 없음"

    ctx = MatcherContext.from_variant(variant)
    matched = match_issues_for_variant(ctx, cache.issues, scenario_id="uc-camera-recording")
    assert isinstance(matched, list)
    # thermal 컨텍스트 없이는 all 조건 실패 → 미매칭
    matched_ids = [m.id for m in matched]
    assert "iss-LLC-thrashing-0221" not in matched_ids


def test_match_issues_wrong_scenario_filtered(engine):
    """다른 scenario_id로 조회하면 issue가 필터링돼야 함."""
    with Session(engine) as session:
        cache = RuleCache.load(session)
        variant = (
            session.query(ScenarioVariant)
            .filter_by(scenario_id="uc-camera-recording", id="UHD60-HDR10-H265")
            .one_or_none()
        )
    assert variant is not None

    ctx = MatcherContext.from_variant(variant)
    matched = match_issues_for_variant(ctx, cache.issues, scenario_id="uc-other-scenario")
    # scenario_ref=uc-camera-recording 이슈는 제외돼야 함
    assert all(m.id != "iss-LLC-thrashing-0221" for m in matched)
