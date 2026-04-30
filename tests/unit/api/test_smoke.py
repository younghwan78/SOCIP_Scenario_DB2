"""
API smoke test — FastAPI dependency override + MagicMock (DB 없이 실행).

전략:
  - get_db: MagicMock session 반환 (query().filter_by().one_or_none() = None)
  - get_rule_cache: 빈 RuleCache(loaded=True)
  - app.state.* 직접 주입

커버리지:
  - 전체 GET 엔드포인트 2xx / 4xx 응답 검증
  - PagedResponse 구조 검증
  - /health/live + /health/ready 응답 구조
  - 404 동작, 400 validation
  - sort_by/sort_dir 파라미터 통과 검증
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from scenario_db.api.app import create_app
from scenario_db.api.cache import RuleCache
from scenario_db.api.deps import get_db, get_rule_cache


# ---------------------------------------------------------------------------
# Mock session 헬퍼
# ---------------------------------------------------------------------------

def _mock_session_empty() -> MagicMock:
    """query(...).filter_by(...).one_or_none() → None, count() → 0, all() → []"""
    session = MagicMock()
    query_mock = MagicMock()
    query_mock.filter_by.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.offset.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.one_or_none.return_value = None
    query_mock.first.return_value = None
    query_mock.all.return_value = []
    query_mock.count.return_value = 0
    session.query.return_value = query_mock
    session.execute.return_value = MagicMock()
    session.close = MagicMock()
    return session


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    app = create_app()

    mock_session = _mock_session_empty()

    @asynccontextmanager
    async def _noop_lifespan(a):
        a.state.engine = None
        a.state.session_factory = lambda: mock_session
        a.state.rule_cache = RuleCache(loaded=True)
        a.state.start_time = time.time()
        yield

    app.router.lifespan_context = _noop_lifespan

    def _override_db():
        yield mock_session

    def _override_cache():
        return RuleCache(loaded=True)

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_rule_cache] = _override_cache

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# /health/live + /health/ready
# ---------------------------------------------------------------------------

def test_health_live(client):
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_structure(client):
    # mock session_factory()는 execute("SELECT 1") 성공 → db_ok=True
    r = client.get("/health/ready")
    body = r.json()
    assert "status" in body
    assert "db" in body
    assert "rule_cache" in body
    assert "uptime_s" in body


def test_health_old_path_404(client):
    """기존 /health 경로는 더 이상 존재하지 않아야 함."""
    r = client.get("/health")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

def test_list_soc_platforms_200(client):
    r = client.get("/api/v1/soc-platforms")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert body["total"] == 0
    assert body["has_next"] is False


def test_get_soc_platform_404(client):
    r = client.get("/api/v1/soc-platforms/nonexistent")
    assert r.status_code == 404


def test_list_ip_catalogs_200(client):
    r = client.get("/api/v1/ip-catalogs")
    assert r.status_code == 200


def test_list_ip_catalogs_invalid_category_400(client):
    r = client.get("/api/v1/ip-catalogs?category=INVALID")
    assert r.status_code == 400


def test_list_ip_catalogs_valid_category_200(client):
    r = client.get("/api/v1/ip-catalogs?category=ISP")
    assert r.status_code == 200


def test_list_sw_profiles_200(client):
    r = client.get("/api/v1/sw-profiles")
    assert r.status_code == 200


def test_list_sw_profiles_valid_flag_200(client):
    r = client.get("/api/v1/sw-profiles?feature_flag=LLC_per_ip_partition:enabled")
    assert r.status_code == 200


def test_list_sw_profiles_invalid_flag_400(client):
    r = client.get("/api/v1/sw-profiles?feature_flag=UNKNOWN_FLAG:enabled")
    assert r.status_code == 400


def test_list_sw_profiles_bad_format_400(client):
    r = client.get("/api/v1/sw-profiles?feature_flag=nocolon")
    assert r.status_code == 400


def test_list_sw_components_200(client):
    r = client.get("/api/v1/sw-components")
    assert r.status_code == 200


def test_list_sw_components_invalid_category_400(client):
    r = client.get("/api/v1/sw-components?category=unknown")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Definition
# ---------------------------------------------------------------------------

def test_list_projects_200(client):
    r = client.get("/api/v1/projects")
    assert r.status_code == 200


def test_list_projects_board_filters_200(client):
    r = client.get("/api/v1/projects?soc_ref=soc-exynos2600&board_type=ERD")
    assert r.status_code == 200


def test_get_project_404(client):
    r = client.get("/api/v1/projects/nonexistent")
    assert r.status_code == 404


def test_list_scenarios_200(client):
    r = client.get("/api/v1/scenarios")
    assert r.status_code == 200


def test_list_scenarios_project_board_filters_200(client):
    r = client.get("/api/v1/scenarios?project_ref=proj-thetis-erd&soc_ref=soc-exynos2600&board_type=ERD")
    assert r.status_code == 200


def test_get_scenario_404(client):
    r = client.get("/api/v1/scenarios/nonexistent")
    assert r.status_code == 404


def test_list_variants_for_unknown_scenario_404(client):
    r = client.get("/api/v1/scenarios/nonexistent/variants")
    assert r.status_code == 404


def test_get_variant_404(client):
    r = client.get("/api/v1/scenarios/s1/variants/v1")
    assert r.status_code == 404


def test_matched_issues_404(client):
    r = client.get("/api/v1/scenarios/nonexistent/variants/v1/matched-issues")
    assert r.status_code == 404


def test_list_all_variants_200(client):
    r = client.get("/api/v1/variants")
    assert r.status_code == 200


def test_list_all_variants_hierarchy_filters_200(client):
    r = client.get("/api/v1/variants?scenario_id=uc-camera&project=proj-thetis-erd&soc_ref=soc-exynos2600&board_type=ERD")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def test_list_evidence_200(client):
    r = client.get("/api/v1/evidence")
    assert r.status_code == 200


def test_get_evidence_404(client):
    r = client.get("/api/v1/evidence/nonexistent")
    assert r.status_code == 404


def test_evidence_summary_200(client):
    r = client.get("/api/v1/evidence/summary")
    assert r.status_code == 200


def test_evidence_summary_invalid_groupby_400(client):
    r = client.get("/api/v1/evidence/summary?groupby=bad_col")
    assert r.status_code == 400


def test_compare_evidence_200(client):
    r = client.get("/api/v1/compare/evidence?variant=v1&sw1=sw-v1&sw2=sw-v2")
    assert r.status_code == 200


def test_compare_variants_200(client):
    r = client.get("/api/v1/compare/variants?ref1=s1::v1&ref2=s2::v2")
    assert r.status_code == 200


def test_compare_variants_bad_ref_400(client):
    r = client.get("/api/v1/compare/variants?ref1=bad&ref2=s2::v2")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_list_reviews_200(client):
    r = client.get("/api/v1/reviews")
    assert r.status_code == 200


def test_get_review_404(client):
    r = client.get("/api/v1/reviews/nonexistent")
    assert r.status_code == 404


def test_list_issues_200(client):
    r = client.get("/api/v1/issues")
    assert r.status_code == 200


def test_get_issue_404(client):
    r = client.get("/api/v1/issues/nonexistent")
    assert r.status_code == 404


def test_list_waivers_200(client):
    r = client.get("/api/v1/waivers")
    assert r.status_code == 200


def test_get_waiver_404(client):
    r = client.get("/api/v1/waivers/nonexistent")
    assert r.status_code == 404


def test_list_gate_rules_200(client):
    r = client.get("/api/v1/gate-rules")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Pagination 구조 + sort 파라미터 통과 검증
# ---------------------------------------------------------------------------

def test_pagination_structure(client):
    r = client.get("/api/v1/evidence?limit=10&offset=5")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    assert body["offset"] == 5
    assert isinstance(body["has_next"], bool)


def test_sort_asc_accepted(client):
    r = client.get("/api/v1/soc-platforms?sort_by=id&sort_dir=asc")
    assert r.status_code == 200


def test_sort_desc_accepted(client):
    r = client.get("/api/v1/ip-catalogs?sort_dir=desc")
    assert r.status_code == 200


def test_sort_invalid_column_400(client):
    r = client.get("/api/v1/soc-platforms?sort_by=nonexistent_col")
    assert r.status_code == 400


def test_sort_invalid_dir_400(client):
    r = client.get("/api/v1/soc-platforms?sort_dir=INVALID")
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Admin 엔드포인트 제거 확인
# ---------------------------------------------------------------------------

def test_admin_cache_refresh_not_exposed(client):
    r = client.post("/api/v1/admin/cache/refresh")
    assert r.status_code in (404, 405)


def test_stub_generate_yaml_not_exposed(client):
    r = client.post("/api/v1/variants/generate-yaml")
    assert r.status_code in (404, 405)
