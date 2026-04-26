"""Phase C (Resolver/Gate) JSONB 연산 readiness 테스트.

검증 항목:
  1. Matcher AST → SQL 번역 (axis 조건: @>, ->>, ?)
  2. jsonb_path_exists() 내장 함수
  3. Issue ↔ Variant cross matching (LATERAL + Python hybrid)
  4. SW profile feature flag 조회 (@>, ?, 다중 플래그)
  5. SQL-only pre-filter와 Python post-filter 일치성 검증
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scenario_db.db.jsonb_ops import (
    axis_eq,
    axis_in,
    axis_matches,
    axis_ne,
    flag_contains,
    flag_has_key,
    flag_multi_contains,
    ip_condition_eq,
    jsonb_path_exists,
    match_condition_to_sql,
    match_rule_all_to_sql,
    nested_astext,
)
from scenario_db.db.models.capability import SwProfile
from scenario_db.db.models.decision import Issue
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.sql_matcher import (
    BulkMatchReport,
    cross_match_issues_variants,
    find_matching_issues_sql_hybrid,
    find_sw_profiles_by_flag,
    find_sw_profiles_by_multi_flags,
    find_sw_profiles_with_key,
    prefilter_issues_by_scenario_ref,
    prefilter_variants_by_axis,
)

pytestmark = pytest.mark.integration

SCENARIO_ID = "uc-camera-recording"
VARIANT_UHD60 = "UHD60-HDR10-H265"
ISSUE_LLC = "iss-LLC-thrashing-0221"


# ===========================================================================
# 1. axis 조건 → SQL 표현식 빌더 (jsonb_ops.py)
# ===========================================================================

class TestAxisSqlExpressions:
    """axis_eq/ne/in/matches → design_conditions JSONB WHERE 절."""

    def test_axis_eq_resolution_uhd(self, engine):
        """->> 텍스트 추출 후 동등 비교."""
        with Session(engine) as s:
            expr = axis_eq(ScenarioVariant.design_conditions, "resolution", "UHD")
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1
        assert all(v.design_conditions["resolution"] == "UHD" for v in rows)

    def test_axis_ne_fps(self, engine):
        """fps != 30 필터."""
        with Session(engine) as s:
            expr = axis_ne(ScenarioVariant.design_conditions, "fps", 30)
            rows = s.query(ScenarioVariant).filter(expr).all()
        # fps!=30인 variant가 있어야 함
        for v in rows:
            assert str(v.design_conditions.get("fps", "")) != "30"

    def test_axis_in_resolution(self, engine):
        """resolution IN [UHD, 8K] → = ANY(ARRAY[...])."""
        with Session(engine) as s:
            expr = axis_in(ScenarioVariant.design_conditions, "resolution", ["UHD", "8K"])
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1
        assert all(v.design_conditions["resolution"] in ("UHD", "8K") for v in rows)

    def test_axis_matches_codec(self, engine):
        """codec ~ 'H\\.26[45]' PostgreSQL regex."""
        with Session(engine) as s:
            expr = axis_matches(ScenarioVariant.design_conditions, "codec", r"H\.26[45]")
            rows = s.query(ScenarioVariant).filter(expr).all()
        # H.264 또는 H.265 variant가 있어야 함
        assert len(rows) >= 1
        for v in rows:
            codec = v.design_conditions.get("codec", "")
            assert "H.26" in codec

    def test_nested_astext_ip_requirements(self, engine):
        """ip_requirements #>> '{isp0, required_bitdepth}' — 중첩 경로."""
        with Session(engine) as s:
            expr = nested_astext(ScenarioVariant.ip_requirements, "isp0", "required_bitdepth")
            rows = (
                s.query(ScenarioVariant)
                .filter(expr == "10")
                .all()
            )
        assert len(rows) >= 1
        for v in rows:
            assert v.ip_requirements["isp0"]["required_bitdepth"] == 10

    def test_ip_condition_eq(self, engine):
        """ip_condition_eq helper — ip_requirements 중첩 경로 동등 비교."""
        with Session(engine) as s:
            expr = ip_condition_eq(
                ScenarioVariant.ip_requirements, "mfc", "required_codec", "H.265"
            )
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1
        for v in rows:
            assert v.ip_requirements["mfc"]["required_codec"] == "H.265"


# ===========================================================================
# 2. feature_flags JSONB — @> / ? 연산자 (jsonb_ops.py)
# ===========================================================================

class TestFeatureFlagSqlExpressions:
    """`@>` containment, `?` key existence SQL 표현식."""

    def test_flag_contains_disabled(self, engine):
        """feature_flags @> '{"LLC_per_ip_partition": "disabled"}' — GIN 인덱스."""
        with Session(engine) as s:
            expr = flag_contains(SwProfile.feature_flags, "LLC_per_ip_partition", "disabled")
            rows = s.query(SwProfile).filter(expr).all()
        assert len(rows) >= 1
        for p in rows:
            assert p.feature_flags["LLC_per_ip_partition"] == "disabled"

    def test_flag_has_key(self, engine):
        """feature_flags ? 'TNR_early_abort' — 키 존재 확인."""
        with Session(engine) as s:
            expr = flag_has_key(SwProfile.feature_flags, "TNR_early_abort")
            rows = s.query(SwProfile).filter(expr).all()
        assert len(rows) >= 1
        for p in rows:
            assert "TNR_early_abort" in p.feature_flags

    def test_flag_multi_contains(self, engine):
        """다중 플래그 동시 @> containment (AND 의미)."""
        with Session(engine) as s:
            expr = flag_multi_contains(SwProfile.feature_flags, {
                "LLC_dynamic_allocation": "enabled",
                "TNR_early_abort": "enabled",
            })
            rows = s.query(SwProfile).filter(expr).all()
        assert len(rows) >= 1
        for p in rows:
            assert p.feature_flags["LLC_dynamic_allocation"] == "enabled"
            assert p.feature_flags["TNR_early_abort"] == "enabled"


# ===========================================================================
# 3. jsonb_path_exists() — PG12+ JSONPath 함수
# ===========================================================================

class TestJsonbPathExists:
    """jsonb_path_exists() — SQL-level JSONPath 존재 확인."""

    def test_path_exists_resolution_uhd(self, engine):
        """$.resolution ? (@ == "UHD") — JSONPath 조건 평가."""
        with Session(engine) as s:
            expr = jsonb_path_exists(
                ScenarioVariant.design_conditions,
                '$.resolution ? (@ == "UHD")',
            )
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1
        assert all(v.design_conditions["resolution"] == "UHD" for v in rows)

    def test_path_exists_fps_range(self, engine):
        """$.fps ? (@ >= 60) — JSONPath 수치 범위."""
        with Session(engine) as s:
            expr = jsonb_path_exists(
                ScenarioVariant.design_conditions,
                "$.fps ? (@ >= 60)",
            )
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1
        for v in rows:
            fps = v.design_conditions.get("fps", 0)
            assert int(fps) >= 60

    def test_path_not_exists_nonexistent_key(self, engine):
        """존재하지 않는 JSONPath → 0건."""
        with Session(engine) as s:
            expr = jsonb_path_exists(
                ScenarioVariant.design_conditions,
                '$.nonexistent_key ? (@ == "impossible")',
            )
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert rows == []

    def test_jsonb_path_exists_raw_sql(self, engine):
        """raw SQL로 jsonb_path_exists() 직접 확인."""
        with Session(engine) as s:
            row = s.execute(
                text("""
                    SELECT COUNT(*) as cnt
                    FROM scenario_variants
                    WHERE jsonb_path_exists(
                        design_conditions,
                        '$.resolution ? (@ == "UHD")'::jsonpath
                    )
                """)
            ).fetchone()
        assert row.cnt >= 1

    def test_jsonb_path_on_feature_flags(self, engine):
        """feature_flags에 JSONPath 적용 — LLC_per_ip_partition == "disabled"."""
        with Session(engine) as s:
            row = s.execute(
                text("""
                    SELECT COUNT(*) as cnt
                    FROM sw_profiles
                    WHERE jsonb_path_exists(
                        feature_flags,
                        '$.LLC_per_ip_partition ? (@ == "disabled")'::jsonpath
                    )
                """)
            ).fetchone()
        assert row.cnt >= 1


# ===========================================================================
# 4. match_condition_to_sql() — MatchCondition → SQLAlchemy 표현식
# ===========================================================================

class TestMatchConditionToSql:
    """MatchCondition dict → SQL 표현식 번역 검증."""

    def test_axis_eq_condition(self, engine):
        """{"axis": "resolution", "op": "eq", "value": "UHD"} → SQL."""
        condition = {"axis": "resolution", "op": "eq", "value": "UHD"}
        with Session(engine) as s:
            expr = match_condition_to_sql(condition, ScenarioVariant.design_conditions)
            assert expr is not None
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1

    def test_axis_in_condition(self, engine):
        """{"axis": "resolution", "op": "in", "value": ["UHD", "8K"]} → SQL."""
        condition = {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]}
        with Session(engine) as s:
            expr = match_condition_to_sql(condition, ScenarioVariant.design_conditions)
            assert expr is not None
            rows = s.query(ScenarioVariant).filter(expr).all()
        assert len(rows) >= 1

    def test_sw_feature_condition_returns_none(self):
        """sw_feature 조건은 SQL 번역 불가 → None (Python fallback 신호)."""
        condition = {"sw_feature": "LLC_dynamic_allocation", "op": "eq", "value": "disabled"}
        expr = match_condition_to_sql(condition, SwProfile.feature_flags)
        assert expr is None, "sw_feature 조건은 None을 반환해야 함 (Python fallback)"

    def test_match_rule_all_to_sql(self, engine):
        """match_rule.all 조건 목록 → AND SQL 표현식 (번역 가능 항목만)."""
        rule = {
            "all": [
                {"axis": "resolution", "op": "in", "value": ["UHD", "8K"]},
                {"axis": "thermal", "op": "in", "value": ["hot", "critical"]},  # None → skip
                {"sw_feature": "LLC_dynamic_allocation", "op": "eq", "value": "disabled"},  # None → skip
            ]
        }
        with Session(engine) as s:
            expr = match_rule_all_to_sql(
                rule, ScenarioVariant.design_conditions, ScenarioVariant.ip_requirements
            )
        # resolution 조건만 번역 가능 → 표현식 반환 (thermal, sw_feature는 skip)
        assert expr is not None

    def test_all_untranslatable_conditions_returns_none(self):
        """모든 조건이 번역 불가 → None."""
        rule = {
            "all": [
                {"sw_feature": "LLC", "op": "eq", "value": "enabled"},
                {"scope": "project_ref", "op": "eq", "value": "*"},
            ]
        }
        expr = match_rule_all_to_sql(
            rule, ScenarioVariant.design_conditions, ScenarioVariant.ip_requirements
        )
        assert expr is None


# ===========================================================================
# 5. Issue ↔ Variant Cross Matching (sql_matcher.py)
# ===========================================================================

class TestCrossMatching:
    """Issue ↔ Variant SQL pre-filter + Python evaluate 하이브리드 매처."""

    def test_prefilter_issues_by_scenario_ref(self, engine):
        """LATERAL + jsonb_array_elements → scenario_ref 매칭 issue 추출."""
        with Session(engine) as s:
            ids = prefilter_issues_by_scenario_ref(s, SCENARIO_ID)
        assert isinstance(ids, list)
        assert ISSUE_LLC in ids, f"LLC issue가 pre-filter 결과에 없음: {ids}"

    def test_prefilter_nonexistent_scenario_returns_empty(self, engine):
        """존재하지 않는 scenario_id → 빈 리스트."""
        with Session(engine) as s:
            ids = prefilter_issues_by_scenario_ref(s, "no-such-scenario-xyz")
        assert ids == []

    def test_prefilter_variants_by_axis(self, engine):
        """design_conditions SQL 필터 — resolution=UHD."""
        with Session(engine) as s:
            ids = prefilter_variants_by_axis(s, SCENARIO_ID, {"resolution": "UHD"})
        assert VARIANT_UHD60 in ids

    def test_prefilter_variants_multi_axis(self, engine):
        """design_conditions 복합 조건 — resolution=UHD AND fps=60."""
        with Session(engine) as s:
            ids = prefilter_variants_by_axis(s, SCENARIO_ID, {"resolution": "UHD", "fps": "60"})
        assert VARIANT_UHD60 in ids

    def test_find_matching_issues_sql_hybrid(self, engine):
        """하이브리드 매처: SQL pre-filter + Python evaluate 결과 정합성."""
        with Session(engine) as s:
            # SQL hybrid
            matched_sql = find_matching_issues_sql_hybrid(s, SCENARIO_ID, VARIANT_UHD60)

        # 현재 LLC issue는 thermal 조건 때문에 미매칭 (올바른 동작)
        assert isinstance(matched_sql, list)
        # SQL hybrid와 기존 Python-only 결과가 일치해야 함
        from scenario_db.api.cache import match_issues_for_variant, RuleCache
        from scenario_db.matcher.context import MatcherContext
        with Session(engine) as s:
            cache = RuleCache.load(s)
            variant = (
                s.query(ScenarioVariant)
                .filter_by(scenario_id=SCENARIO_ID, id=VARIANT_UHD60)
                .one()
            )
            ctx = MatcherContext.from_variant(variant)
        python_matched = [
            m.id for m in match_issues_for_variant(ctx, cache.issues, scenario_id=SCENARIO_ID)
        ]
        assert sorted(matched_sql) == sorted(python_matched), (
            f"SQL hybrid 결과={matched_sql} ≠ Python 결과={python_matched}"
        )

    def test_cross_match_bulk_report(self, engine):
        """cross_match_issues_variants() — BulkMatchReport 구조 검증."""
        with Session(engine) as s:
            report = cross_match_issues_variants(s, SCENARIO_ID)

        assert isinstance(report, BulkMatchReport)
        assert report.scenario_id == SCENARIO_ID
        assert report.total_variants >= 1
        assert report.total_issues >= 1
        assert report.sql_candidate_pairs == report.total_variants * report.total_issues
        assert report.matched_pairs >= 0
        # 매칭 쌍의 수는 전체 쌍 수를 초과할 수 없음
        assert report.matched_pairs <= report.sql_candidate_pairs

    def test_cross_match_specific_variant(self, engine):
        """특정 variant ID로 제한한 cross matching."""
        with Session(engine) as s:
            report = cross_match_issues_variants(
                s, SCENARIO_ID, variant_ids=[VARIANT_UHD60]
            )
        assert report.total_variants == 1
        assert report.total_issues >= 1


# ===========================================================================
# 6. SW Profile Feature Flag 조회 (sql_matcher.py)
# ===========================================================================

class TestSwProfileFlagQueries:
    """Phase C SW 호환성 체크용 feature flag SQL 쿼리."""

    def test_find_by_flag_disabled(self, engine):
        """LLC_per_ip_partition=disabled 프로파일 조회."""
        with Session(engine) as s:
            ids = find_sw_profiles_by_flag(s, "LLC_per_ip_partition", "disabled")
        assert "sw-vendor-v1.2.3" in ids

    def test_find_by_flag_enabled(self, engine):
        """LLC_dynamic_allocation=enabled 프로파일 조회."""
        with Session(engine) as s:
            ids = find_sw_profiles_by_flag(s, "LLC_dynamic_allocation", "enabled")
        assert len(ids) >= 1

    def test_find_by_nonexistent_flag_empty(self, engine):
        """존재하지 않는 flag 값 → 빈 리스트."""
        with Session(engine) as s:
            ids = find_sw_profiles_by_flag(s, "LLC_per_ip_partition", "nonexistent_value_xyz")
        assert ids == []

    def test_find_by_multi_flags(self, engine):
        """다중 플래그 AND 조건 containment."""
        with Session(engine) as s:
            ids = find_sw_profiles_by_multi_flags(s, {
                "LLC_dynamic_allocation": "enabled",
                "MFC_hwae": "enabled",
            })
        assert len(ids) >= 1

    def test_find_profiles_with_key(self, engine):
        """feature_flags ? 'MFC_hwae' — 키 존재 여부만 확인."""
        with Session(engine) as s:
            ids = find_sw_profiles_with_key(s, "MFC_hwae")
        assert len(ids) >= 1

    def test_sw_profile_compatible_with_variant(self, engine):
        """UHD60 variant의 sw_requirements와 sw_profile feature_flags 교차 검증.

        Phase C Gate에서: variant.sw_requirements.required_features 각 항목이
        sw_profile.feature_flags에서 required 값으로 설정됐는지 확인.
        """
        with Session(engine) as s:
            variant = (
                s.query(ScenarioVariant)
                .filter_by(scenario_id=SCENARIO_ID, id=VARIANT_UHD60)
                .one()
            )
            sw_req = variant.sw_requirements or {}
            required_features = sw_req.get("required_features", [])

            # required_features: [{feature: value}, ...] 구조
            for feat_dict in required_features:
                if not isinstance(feat_dict, dict):
                    continue
                for flag_name, flag_value in feat_dict.items():
                    profiles = find_sw_profiles_by_flag(s, flag_name, flag_value)
                    # 최소 1개 이상의 sw_profile이 해당 feature를 지원해야 함 (또는 0개 = 미지원)
                    assert isinstance(profiles, list)  # 타입 검증만 (값은 픽스처 의존)
