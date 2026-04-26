"""자주 쓰는 쿼리 모음 — notebooks에서 직접 호출."""
from __future__ import annotations

import pandas as pd

from .db_connection import get_engine, query_df


# ---------------------------------------------------------------------------
# 메타 쿼리
# ---------------------------------------------------------------------------

def table_counts(engine=None) -> pd.DataFrame:
    """모든 주요 테이블의 레코드 수 반환."""
    tables = [
        "soc_platforms", "ip_catalog", "sw_profiles", "sw_components",
        "projects", "scenarios", "scenario_variants",
        "evidence", "gate_rules", "issues", "waivers", "reviews",
    ]
    rows = []
    eng = engine or get_engine()
    from sqlalchemy import text
    with eng.connect() as conn:
        for t in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            rows.append({"table": t, "count": n})
    return pd.DataFrame(rows)


def sample_rows(table: str, n: int = 1, engine=None) -> pd.DataFrame:
    """테이블에서 n개 샘플 행 반환."""
    return query_df(f"SELECT * FROM {table} LIMIT {n}", engine)


# ---------------------------------------------------------------------------
# Capability 쿼리
# ---------------------------------------------------------------------------

def list_ips(engine=None) -> pd.DataFrame:
    return query_df("""
        SELECT id, category, rtl_version,
               jsonb_array_length(compatible_soc) AS soc_count,
               hierarchy->>'type' AS hierarchy_type
        FROM ip_catalog
        ORDER BY category, id
    """, engine)


def list_sw_profiles(engine=None) -> pd.DataFrame:
    return query_df("""
        SELECT id,
               metadata->>'version'      AS version,
               metadata->>'release_type' AS release_type,
               metadata->>'release_date' AS release_date,
               feature_flags->>'LLC_per_ip_partition' AS llc_per_ip_partition,
               jsonb_array_length(
                   COALESCE(known_issues_at_release, '[]'::jsonb)
               ) AS known_issue_count
        FROM sw_profiles
        ORDER BY metadata->>'release_date'
    """, engine)


# ---------------------------------------------------------------------------
# Definition 쿼리
# ---------------------------------------------------------------------------

def list_variants(scenario_id: str | None = None, engine=None) -> pd.DataFrame:
    where = f"WHERE scenario_id = '{scenario_id}'" if scenario_id else ""
    return query_df(f"""
        SELECT scenario_id, id AS variant_id, severity,
               jsonb_array_length(COALESCE(tags, '[]'::jsonb)) AS tag_count,
               derived_from_variant
        FROM scenario_variants
        {where}
        ORDER BY scenario_id, id
    """, engine)


# ---------------------------------------------------------------------------
# Evidence 쿼리
# ---------------------------------------------------------------------------

def evidence_summary(engine=None) -> pd.DataFrame:
    """kind / feasibility / sw_version 별 집계."""
    return query_df("""
        SELECT kind,
               overall_feasibility,
               sw_version_hint,
               COUNT(*)                            AS cnt,
               AVG((kpi->>'total_power_mw')::float) AS avg_power_mw,
               MAX((kpi->>'peak_power_mw')::float)  AS max_peak_power_mw
        FROM evidence
        GROUP BY kind, overall_feasibility, sw_version_hint
        ORDER BY kind, sw_version_hint
    """, engine)


def compare_sw_versions(scenario_ref: str, variant_ref: str,
                        engine=None) -> pd.DataFrame:
    """동일 시나리오/variant의 sw 버전별 KPI 비교 (simulation만)."""
    return query_df("""
        SELECT sw_version_hint,
               overall_feasibility,
               (kpi->>'total_power_mw')::float  AS total_power_mw,
               (kpi->>'peak_power_mw')::float   AS peak_power_mw,
               (kpi->>'avg_ddr_bw_gbps')::float AS avg_ddr_bw_gbps,
               (kpi->>'peak_ddr_bw_gbps')::float AS peak_ddr_bw_gbps,
               (kpi->>'frame_latency_ms')::float AS frame_latency_ms
        FROM evidence
        WHERE kind        = 'evidence.simulation'
          AND scenario_ref = :scenario_ref
          AND variant_ref  = :variant_ref
        ORDER BY sw_version_hint
    """, engine,
    scenario_ref=scenario_ref, variant_ref=variant_ref)


def violation_detail(engine=None) -> pd.DataFrame:
    """sw resolution violations 상세 (JSON 배열 UNNEST)."""
    return query_df("""
        SELECT id AS evidence_id,
               sw_version_hint,
               overall_feasibility,
               (resolution_result->'sw_resolution'->>'profile_ref') AS profile_ref,
               v->>'feature'      AS violated_feature,
               v->>'required'     AS required,
               v->>'actual'       AS actual,
               v->>'action_taken' AS action_taken
        FROM evidence,
             jsonb_array_elements(
                 resolution_result->'sw_resolution'->'violations'
             ) AS v
        WHERE kind = 'evidence.simulation'
        ORDER BY evidence_id
    """, engine)


# ---------------------------------------------------------------------------
# Decision 쿼리
# ---------------------------------------------------------------------------

def review_summary(engine=None) -> pd.DataFrame:
    return query_df("""
        SELECT r.id,
               r.scenario_ref,
               r.variant_ref,
               r.gate_result,
               r.decision,
               r.status,
               r.waiver_ref,
               w.expires_on        AS waiver_expires,
               r.approver_claim,
               r.claim_at
        FROM reviews r
        LEFT JOIN waivers w ON w.id = r.waiver_ref
        ORDER BY r.claim_at DESC
    """, engine)


def open_issues(engine=None) -> pd.DataFrame:
    return query_df("""
        SELECT id,
               metadata->>'title'    AS title,
               metadata->>'severity' AS severity,
               metadata->>'status'   AS status,
               resolution->>'fix_sw_ref' AS fixed_in_sw
        FROM issues
        WHERE metadata->>'status' != 'resolved'
          OR  metadata->>'status' IS NULL
        ORDER BY metadata->>'severity' DESC
    """, engine)


def waiver_expiry_check(engine=None) -> pd.DataFrame:
    """만료일이 90일 이내인 waiver 경고."""
    return query_df("""
        SELECT id, title, status, expires_on,
               expires_on - CURRENT_DATE AS days_remaining
        FROM waivers
        WHERE expires_on IS NOT NULL
          AND expires_on - CURRENT_DATE <= 90
        ORDER BY expires_on
    """, engine)
