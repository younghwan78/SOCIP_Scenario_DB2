"""SQL-level Bulk Matcher — Phase C (Resolver/Gate) 대비.

하이브리드 전략:
  1. SQL pre-filter : scenario_ref 매칭 (LATERAL + jsonb_array_elements)
                     + axis 조건 일부를 SQL WHERE로 번역 (design_conditions JSONB)
  2. Python post-filter : sw_feature / sw_conditions / ip sub-field 조건
                          (현재 matcher.runner.evaluate() 재사용)

이 전략의 이유:
  - sw_feature 조건은 sw_profiles JOIN 필요 → 순수 SQL 번역 불가
  - Phase C 규모(수백 variant × 수십 issue)에서 충분히 빠름
  - Phase D에서 PL/pgSQL 함수로 전환할 수 있는 명확한 경계
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from scenario_db.db.jsonb_ops import match_rule_all_to_sql
from scenario_db.db.models.capability import SwProfile
from scenario_db.db.models.decision import Issue
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.matcher.context import MatcherContext
from scenario_db.matcher.runner import evaluate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 결과 타입
# ---------------------------------------------------------------------------

@dataclass
class VariantMatchResult:
    """단일 (variant, issue) 매칭 결과."""
    variant_id: str
    issue_id: str
    scenario_id: str
    matched: bool
    sql_prefiltered: bool   # SQL pre-filter 통과 여부
    python_evaluated: bool  # Python AST 평가 여부


@dataclass
class BulkMatchReport:
    """전체 bulk 매칭 결과 요약."""
    scenario_id: str
    total_variants: int
    total_issues: int
    sql_candidate_pairs: int   # SQL pre-filter 통과 (variant, issue) 쌍 수
    matched_pairs: int         # 최종 매칭 쌍 수
    results: list[VariantMatchResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SQL pre-filter
# ---------------------------------------------------------------------------

def prefilter_issues_by_scenario_ref(
    session: Session,
    scenario_id: str,
) -> list[str]:
    """
    LATERAL + jsonb_array_elements를 사용해 scenario_ref가 일치하는 Issue ID 추출.

    SQL:
        SELECT DISTINCT i.id
        FROM issues i,
        LATERAL jsonb_array_elements(i.affects) AS affect
        WHERE affect->>'scenario_ref' = :sid
           OR affect->>'scenario_ref' = '*'

    Returns: issue ID 목록.
    """
    rows = session.execute(
        text("""
            SELECT DISTINCT i.id
            FROM issues i,
            LATERAL jsonb_array_elements(i.affects) AS affect
            WHERE affect->>'scenario_ref' = :sid
               OR affect->>'scenario_ref' = '*'
        """),
        {"sid": scenario_id},
    ).fetchall()
    return [r[0] for r in rows]


def prefilter_variants_by_axis(
    session: Session,
    scenario_id: str,
    axis_conditions: dict[str, str],
) -> list[str]:
    """
    design_conditions JSONB를 SQL로 필터링해 조건을 만족하는 Variant ID 추출.

    Args:
        axis_conditions: {axis_name: expected_value} 딕셔너리.
            예) {"resolution": "UHD", "fps": "60"}

    SQL 생성 예:
        WHERE design_conditions->>'resolution' = 'UHD'
          AND design_conditions->>'fps' = '60'
    """
    q = session.query(ScenarioVariant).filter_by(scenario_id=scenario_id)
    for axis, value in axis_conditions.items():
        q = q.filter(ScenarioVariant.design_conditions[axis].astext == str(value))
    return [v.id for v in q.all()]


# ---------------------------------------------------------------------------
# Cross-matching: Issue ↔ Variant
# ---------------------------------------------------------------------------

def cross_match_issues_variants(
    session: Session,
    scenario_id: str,
    variant_ids: list[str] | None = None,
    issue_ids: list[str] | None = None,
) -> BulkMatchReport:
    """
    지정 scenario 내 모든 (variant, issue) 쌍에 대해 매칭 평가.

    Step 1 (SQL):   scenario_ref pre-filter로 candidate issue 추출
    Step 2 (SQL):   variant 목록 조회 (optional variant_ids 필터)
    Step 3 (Python): MatcherContext 생성 후 evaluate() 호출

    Args:
        variant_ids: None이면 시나리오의 모든 variant 대상.
        issue_ids:   None이면 scenario_ref가 매칭되는 모든 issue 대상.

    Returns: BulkMatchReport
    """
    # --- 후보 issue 목록 ---
    candidate_issue_ids = issue_ids or prefilter_issues_by_scenario_ref(session, scenario_id)
    if not candidate_issue_ids:
        logger.debug("no candidate issues for scenario=%s", scenario_id)
        return BulkMatchReport(scenario_id=scenario_id, total_variants=0,
                               total_issues=0, sql_candidate_pairs=0, matched_pairs=0)

    candidate_issues = (
        session.query(Issue)
        .filter(Issue.id.in_(candidate_issue_ids))
        .all()
    )

    # --- 대상 variant 목록 ---
    variant_q = session.query(ScenarioVariant).filter_by(scenario_id=scenario_id)
    if variant_ids:
        variant_q = variant_q.filter(ScenarioVariant.id.in_(variant_ids))
    variants = variant_q.all()

    report = BulkMatchReport(
        scenario_id=scenario_id,
        total_variants=len(variants),
        total_issues=len(candidate_issues),
        sql_candidate_pairs=len(variants) * len(candidate_issues),
        matched_pairs=0,
    )

    # --- Python evaluate ---
    for variant in variants:
        ctx = MatcherContext.from_variant(variant)
        for issue in candidate_issues:
            if not issue.affects:
                continue
            for affect in issue.affects:
                if not isinstance(affect, dict):
                    continue
                ref = affect.get("scenario_ref", "*")
                if ref != "*" and ref != scenario_id:
                    continue
                match_rule = affect.get("match_rule")
                matched = not match_rule or evaluate(match_rule, ctx)
                if matched:
                    report.matched_pairs += 1
                    report.results.append(VariantMatchResult(
                        variant_id=variant.id,
                        issue_id=issue.id,
                        scenario_id=scenario_id,
                        matched=True,
                        sql_prefiltered=True,
                        python_evaluated=True,
                    ))
                    break  # 한 affect 항목이 매칭되면 충분

    return report


# ---------------------------------------------------------------------------
# SW Profile Feature Flag 필터
# ---------------------------------------------------------------------------

def find_sw_profiles_by_flag(
    session: Session,
    flag_name: str,
    flag_value: str,
) -> list[str]:
    """
    feature_flags @> '{"flag_name": "flag_value"}'::jsonb — GIN 인덱스 사용.

    Phase C SW 호환성 체크: 특정 feature flag 값을 가진 SW profile 조회.

    Returns: SwProfile ID 목록.
    """
    results = (
        session.query(SwProfile)
        .filter(SwProfile.feature_flags.contains({flag_name: flag_value}))
        .all()
    )
    return [p.id for p in results]


def find_sw_profiles_by_multi_flags(
    session: Session,
    flags: dict[str, str],
) -> list[str]:
    """
    다중 feature flag 동시 containment — 모든 플래그가 AND 조건으로 매칭.

    SQL: feature_flags @> '{"k1": "v1", "k2": "v2"}'::jsonb
    """
    results = (
        session.query(SwProfile)
        .filter(SwProfile.feature_flags.contains(flags))
        .all()
    )
    return [p.id for p in results]


def find_sw_profiles_with_key(
    session: Session,
    flag_key: str,
) -> list[str]:
    """
    feature_flags ? 'key' — 키 존재 여부만 확인.
    값과 무관하게 해당 플래그가 정의된 SW profile 반환.
    """
    results = (
        session.query(SwProfile)
        .filter(SwProfile.feature_flags.has_key(flag_key))
        .all()
    )
    return [p.id for p in results]


# ---------------------------------------------------------------------------
# SQL-only 단일 variant 매칭 (axis 조건만 SQL 번역)
# ---------------------------------------------------------------------------

def find_matching_issues_sql_hybrid(
    session: Session,
    scenario_id: str,
    variant_id: str,
) -> list[str]:
    """
    단일 variant에 대한 하이브리드 매칭.

    Step 1 (SQL): LATERAL로 scenario_ref 매칭 issue 후보 추출
    Step 2 (Python): 전체 AST 평가

    Returns: 매칭된 issue ID 목록.
    """
    candidate_ids = prefilter_issues_by_scenario_ref(session, scenario_id)
    if not candidate_ids:
        return []

    variant = (
        session.query(ScenarioVariant)
        .filter_by(scenario_id=scenario_id, id=variant_id)
        .one_or_none()
    )
    if variant is None:
        return []

    candidates = session.query(Issue).filter(Issue.id.in_(candidate_ids)).all()
    ctx = MatcherContext.from_variant(variant)

    matched_ids = []
    for issue in candidates:
        if not issue.affects:
            continue
        for affect in issue.affects:
            if not isinstance(affect, dict):
                continue
            ref = affect.get("scenario_ref", "*")
            if ref != "*" and ref != scenario_id:
                continue
            match_rule = affect.get("match_rule")
            if not match_rule or evaluate(match_rule, ctx):
                matched_ids.append(issue.id)
                break
    return matched_ids
