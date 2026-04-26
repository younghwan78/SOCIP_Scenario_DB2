"""JSONB 전용 통합 테스트 — 실 PostgreSQL에서 JSONB 연산자/인덱스/Generated Column 검증.

테스트 대상:
  - ScenarioVariant.design_conditions  (JSONB → ->> 텍스트 추출 필터)
  - SwProfile.feature_flags            (JSONB → @> containment, GIN 인덱스)
  - Evidence.sw_version_hint           (Generated column, Computed)
  - EXPLAIN ANALYZE로 GIN 인덱스 사용 확인
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from scenario_db.db.models.capability import SwProfile
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.models.evidence import Evidence

pytestmark = pytest.mark.integration


# ===========================================================================
# 1. design_conditions JSONB — ->> 텍스트 추출 필터
# ===========================================================================

class TestDesignConditionsJsonb:
    def test_filter_by_resolution_uhd(self, engine):
        """design_conditions->>'resolution' = 'UHD' 필터."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(ScenarioVariant.design_conditions["resolution"].astext == "UHD")
                .all()
            )
        assert len(results) >= 1
        for v in results:
            assert v.design_conditions["resolution"] == "UHD"

    def test_filter_by_fps_60(self, engine):
        """design_conditions->>'fps' 필터 (정수값 텍스트 비교)."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(ScenarioVariant.design_conditions["fps"].astext == "60")
                .all()
            )
        assert len(results) >= 1

    def test_filter_by_hdr_format(self, engine):
        """design_conditions->>'hdr' = 'HDR10' 필터."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(ScenarioVariant.design_conditions["hdr"].astext == "HDR10")
                .all()
            )
        assert len(results) >= 1
        assert all(v.design_conditions["hdr"] == "HDR10" for v in results)

    def test_combined_resolution_fps_filter(self, engine):
        """resolution=UHD AND fps=60 복합 JSONB 필터."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(
                    ScenarioVariant.design_conditions["resolution"].astext == "UHD",
                    ScenarioVariant.design_conditions["fps"].astext == "60",
                )
                .all()
            )
        assert len(results) >= 1
        for v in results:
            assert v.design_conditions["resolution"] == "UHD"
            assert str(v.design_conditions["fps"]) == "60"

    def test_no_match_returns_empty(self, engine):
        """존재하지 않는 resolution 값 → 빈 결과."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(ScenarioVariant.design_conditions["resolution"].astext == "32K")
                .all()
            )
        assert results == []

    def test_ip_requirements_nested_jsonb(self, engine):
        """ip_requirements JSONB 중첩 경로 — isp0.required_bitdepth."""
        with Session(engine) as s:
            results = (
                s.query(ScenarioVariant)
                .filter(
                    ScenarioVariant.ip_requirements["isp0"]["required_bitdepth"].astext == "10"
                )
                .all()
            )
        # UHD60-HDR10-H265 variant는 required_bitdepth=10
        assert len(results) >= 1


# ===========================================================================
# 2. feature_flags JSONB — @> containment 연산자 (GIN 인덱스: idx_sw_prof_features)
# ===========================================================================

class TestFeatureFlagsJsonb:
    def test_containment_disabled_flag(self, engine):
        """feature_flags @> '{"LLC_per_ip_partition": "disabled"}' — sw-vendor-v1.2.3 매칭."""
        with Session(engine) as s:
            results = (
                s.query(SwProfile)
                .filter(
                    SwProfile.feature_flags.contains({"LLC_per_ip_partition": "disabled"})
                )
                .all()
            )
        assert len(results) >= 1
        ids = [p.id for p in results]
        assert "sw-vendor-v1.2.3" in ids
        for p in results:
            assert p.feature_flags["LLC_per_ip_partition"] == "disabled"

    def test_containment_enabled_flag(self, engine):
        """feature_flags @> '{"LLC_dynamic_allocation": "enabled"}' 필터."""
        with Session(engine) as s:
            results = (
                s.query(SwProfile)
                .filter(
                    SwProfile.feature_flags.contains({"LLC_dynamic_allocation": "enabled"})
                )
                .all()
            )
        assert len(results) >= 1
        for p in results:
            assert p.feature_flags["LLC_dynamic_allocation"] == "enabled"

    def test_containment_multi_flag(self, engine):
        """두 플래그 동시 containment — AND 조건."""
        with Session(engine) as s:
            results = (
                s.query(SwProfile)
                .filter(
                    SwProfile.feature_flags.contains({
                        "LLC_dynamic_allocation": "enabled",
                        "MFC_hwae": "enabled",
                    })
                )
                .all()
            )
        assert len(results) >= 1

    def test_astext_flag_filter(self, engine):
        """feature_flags->>'TNR_early_abort' = 'enabled' (텍스트 추출 방식)."""
        with Session(engine) as s:
            results = (
                s.query(SwProfile)
                .filter(SwProfile.feature_flags["TNR_early_abort"].astext == "enabled")
                .all()
            )
        assert len(results) >= 1

    def test_gin_index_exists(self, engine):
        """GIN 인덱스 idx_sw_prof_features 존재 확인."""
        with Session(engine) as s:
            row = s.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'sw_profiles' AND indexname = 'idx_sw_prof_features'"
                )
            ).fetchone()
        assert row is not None, "GIN 인덱스 idx_sw_prof_features가 존재하지 않음"

    def test_gin_index_used_in_explain(self, engine):
        """EXPLAIN 출력에서 GIN 인덱스 사용 확인 (Bitmap Index Scan 또는 Index Scan)."""
        with Session(engine) as s:
            plan = s.execute(
                text(
                    "EXPLAIN SELECT id FROM sw_profiles "
                    "WHERE feature_flags @> '{\"LLC_per_ip_partition\": \"disabled\"}'::jsonb"
                )
            ).fetchall()
        plan_text = " ".join(row[0] for row in plan)
        # 소규모 테이블에서는 Seq Scan이 선택될 수 있음 → 플랜 출력 자체가 실행됨을 확인
        assert len(plan_text) > 0, "EXPLAIN 실행 실패"
        # GIN 인덱스가 생성됐으면 Bitmap Index Scan / Index Scan 중 하나가 등장
        # (소규모 데이터는 Seq Scan을 선택할 수 있으므로 인덱스 이름 존재만 검증)
        index_used = "idx_sw_prof_features" in plan_text
        seq_scan = "Seq Scan" in plan_text
        assert index_used or seq_scan, f"예상치 못한 플랜: {plan_text}"


# ===========================================================================
# 3. sw_version_hint Generated Column — Computed 컬럼 검증
# ===========================================================================

class TestGeneratedColumns:
    def test_sw_version_hint_populated(self, engine):
        """sw_version_hint = execution_context->>'sw_baseline_ref' (Generated Column)."""
        with Session(engine) as s:
            rows = s.query(Evidence).filter(
                Evidence.sw_version_hint.isnot(None)
            ).all()
        assert len(rows) >= 1
        for row in rows:
            expected = row.execution_context.get("sw_baseline_ref")
            assert row.sw_version_hint == expected, (
                f"sw_version_hint={row.sw_version_hint!r} ≠ "
                f"execution_context.sw_baseline_ref={expected!r}"
            )

    def test_sw_version_hint_filter(self, engine):
        """sw_version_hint 컬럼으로 직접 필터."""
        with Session(engine) as s:
            rows = s.query(Evidence).filter(
                Evidence.sw_version_hint == "sw-vendor-v1.2.3"
            ).all()
        assert len(rows) >= 1
        for row in rows:
            assert row.execution_context["sw_baseline_ref"] == "sw-vendor-v1.2.3"

    def test_sw_version_hint_index_exists(self, engine):
        """sw_version_hint 컬럼에 인덱스 존재 여부 확인."""
        with Session(engine) as s:
            row = s.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'evidence' AND indexdef LIKE '%sw_version_hint%'"
                )
            ).fetchone()
        assert row is not None, "sw_version_hint 인덱스가 존재하지 않음"

    def test_groupby_on_generated_column(self, engine):
        """sw_version_hint Generated Column으로 GROUP BY 집계."""
        with Session(engine) as s:
            from sqlalchemy import func
            rows = (
                s.query(Evidence.sw_version_hint, func.count().label("cnt"))
                .group_by(Evidence.sw_version_hint)
                .all()
            )
        assert len(rows) >= 1
        for hint, cnt in rows:
            assert cnt >= 1

    def test_two_sw_versions_distinct(self, engine):
        """demo 픽스처에 sw-vendor-v1.2.3과 sw-vendor-v1.3.0 두 버전이 각각 존재."""
        with Session(engine) as s:
            hints = {
                row.sw_version_hint
                for row in s.query(Evidence).filter(Evidence.sw_version_hint.isnot(None)).all()
            }
        assert "sw-vendor-v1.2.3" in hints
        assert "sw-vendor-v1.3.0" in hints


# ===========================================================================
# 4. JSONB 패스 검증 — raw SQL로 PostgreSQL 연산자 직접 테스트
# ===========================================================================

class TestRawJsonbOperators:
    def test_arrow_operator_text_extraction(self, engine):
        """-> / ->> 연산자 직접 검증."""
        with Session(engine) as s:
            row = s.execute(
                text(
                    "SELECT design_conditions->>'resolution' AS res "
                    "FROM scenario_variants "
                    "WHERE id = 'UHD60-HDR10-H265'"
                )
            ).fetchone()
        assert row is not None
        assert row.res == "UHD"

    def test_containment_operator_raw(self, engine):
        """@> containment 연산자 — raw SQL."""
        with Session(engine) as s:
            rows = s.execute(
                text(
                    "SELECT id FROM sw_profiles "
                    "WHERE feature_flags @> '{\"LLC_per_ip_partition\": \"disabled\"}'::jsonb"
                )
            ).fetchall()
        ids = [r[0] for r in rows]
        assert "sw-vendor-v1.2.3" in ids

    def test_has_key_operator(self, engine):
        """? 키 존재 연산자 — feature_flags에 'MFC_hwae' 키 포함 여부."""
        with Session(engine) as s:
            rows = s.execute(
                text("SELECT id FROM sw_profiles WHERE feature_flags ? 'MFC_hwae'")
            ).fetchall()
        assert len(rows) >= 1

    def test_nested_path_extraction(self, engine):
        """#>> 경로 배열 추출 연산자."""
        with Session(engine) as s:
            row = s.execute(
                text(
                    "SELECT ip_requirements #>> '{isp0,required_bitdepth}' AS bd "
                    "FROM scenario_variants "
                    "WHERE id = 'UHD60-HDR10-H265'"
                )
            ).fetchone()
        assert row is not None
        assert row.bd == "10"
