"""JSONB 핵심 엔드포인트 — /variants/{sid}/{vid}/matched-issues 실 DB 검증."""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

SCENARIO_ID = "uc-camera-recording"
VARIANT_ID = "UHD60-HDR10-H265"
BASE = f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/matched-issues"


def test_endpoint_returns_200(api_client: TestClient):
    resp = api_client.get(BASE)
    assert resp.status_code == 200


def test_response_structure(api_client: TestClient):
    resp = api_client.get(BASE)
    data = resp.json()
    assert "matched" in data
    assert "total" in data
    assert "eval_time_ms" in data
    assert isinstance(data["matched"], list)
    assert isinstance(data["total"], int)
    assert isinstance(data["eval_time_ms"], float)


def test_llc_issue_not_matched_without_thermal(api_client: TestClient):
    """LLC thrashing issue의 all 조건에 thermal=[hot,critical]이 포함됨.

    UHD60 variant의 design_conditions에는 thermal이 없으므로
    MatcherContext.axis.thermal=None → all 조건 실패 → 미매칭이 올바른 동작.
    """
    resp = api_client.get(BASE)
    data = resp.json()
    ids = [m["id"] for m in data["matched"]]
    assert "iss-LLC-thrashing-0221" not in ids, (
        f"thermal 없이 LLC thrashing issue가 매칭됨 (예상치 못한 매칭): {ids}"
    )


def test_total_matches_list_length(api_client: TestClient):
    resp = api_client.get(BASE)
    data = resp.json()
    assert data["total"] == len(data["matched"])


def test_eval_time_is_positive(api_client: TestClient):
    resp = api_client.get(BASE)
    assert resp.json()["eval_time_ms"] >= 0.0


def test_404_on_unknown_variant(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/no-such-variant/matched-issues")
    assert resp.status_code == 404


def test_404_on_unknown_scenario(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/no-such-scenario/variants/{VARIANT_ID}/matched-issues")
    assert resp.status_code == 404
