"""Decision 레이어 API — 캐시 우선 서빙 + 실 DB 검증."""
import pytest
from fastapi.testclient import TestClient

from scenario_db.api.cache import RuleCache

pytestmark = pytest.mark.integration

ISSUE_ID = "iss-LLC-thrashing-0221"
WAIVER_ID = "waiver-LLC-thrashing-UHD60-A0-20260417"


def test_cache_is_loaded(rule_cache: RuleCache):
    """통합 환경에서 RuleCache는 반드시 loaded=True여야 함."""
    assert rule_cache.loaded is True
    assert rule_cache.load_error is None


def test_issues_served_from_cache(api_client: TestClient, rule_cache: RuleCache):
    resp = api_client.get("/api/v1/issues")
    assert resp.status_code == 200
    data = resp.json()
    # 캐시 경로: total == len(cache.issues)
    assert data["total"] == len(rule_cache.issues)


def test_get_specific_issue(api_client: TestClient):
    resp = api_client.get(f"/api/v1/issues/{ISSUE_ID}")
    assert resp.status_code == 200
    issue = resp.json()
    assert issue["id"] == ISSUE_ID
    assert isinstance(issue["affects"], list)
    assert isinstance(issue["pmu_signature"], list)


def test_issue_404(api_client: TestClient):
    resp = api_client.get("/api/v1/issues/no-such-issue")
    assert resp.status_code == 404


def test_waivers_list(api_client: TestClient):
    resp = api_client.get("/api/v1/waivers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    ids = [w["id"] for w in data["items"]]
    assert WAIVER_ID in ids


def test_get_specific_waiver(api_client: TestClient):
    resp = api_client.get(f"/api/v1/waivers/{WAIVER_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == WAIVER_ID


def test_gate_rules_served_from_cache(api_client: TestClient, rule_cache: RuleCache):
    resp = api_client.get("/api/v1/gate-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(rule_cache.gate_rules)
    assert data["total"] >= 1


def test_reviews_list(api_client: TestClient):
    resp = api_client.get("/api/v1/reviews")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
