"""Definition 레이어 API — 실 DB 검증."""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

SCENARIO_ID = "uc-camera-recording"
VARIANT_ID = "UHD60-HDR10-H265"


def test_list_projects(api_client: TestClient):
    resp = api_client.get("/api/v1/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(p["id"] == "proj-A-exynos2500" for p in data["items"])


def test_get_project_by_id(api_client: TestClient):
    resp = api_client.get("/api/v1/projects/proj-A-exynos2500")
    assert resp.status_code == 200
    assert resp.json()["id"] == "proj-A-exynos2500"


def test_get_project_404(api_client: TestClient):
    resp = api_client.get("/api/v1/projects/no-such-project")
    assert resp.status_code == 404


def test_list_scenarios(api_client: TestClient):
    resp = api_client.get("/api/v1/scenarios")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(s["id"] == SCENARIO_ID for s in data["items"])


def test_get_scenario_by_id(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == SCENARIO_ID


def test_get_scenario_404(api_client: TestClient):
    resp = api_client.get("/api/v1/scenarios/no-such-scenario")
    assert resp.status_code == 404


def test_list_variants_for_scenario(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    ids = [v["id"] for v in data["items"]]
    assert VARIANT_ID in ids


def test_get_specific_variant(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}")
    assert resp.status_code == 200
    v = resp.json()
    assert v["id"] == VARIANT_ID
    assert v["scenario_id"] == SCENARIO_ID


def test_get_derived_variant_returns_resolved_overlay(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/UHD60-HDR10-sustained-10min")
    assert resp.status_code == 200
    v = resp.json()
    assert v["id"] == "UHD60-HDR10-sustained-10min"
    assert v["derived_from_variant"] == VARIANT_ID
    assert v["resolved"] is True
    assert v["inheritance_chain"] == [VARIANT_ID, "UHD60-HDR10-sustained-10min"]
    assert v["design_conditions"]["resolution"] == "UHD"
    assert v["design_conditions"]["fps"] == 60
    assert v["design_conditions"]["duration_category"] == "sustained_10min"
    assert v["size_overrides"]["record_out"] == "3840x2160"
    assert v["ip_requirements"]["mfc"]["required_codec"] == "H.265"


def test_get_variant_404(api_client: TestClient):
    resp = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/no-such-variant")
    assert resp.status_code == 404


def test_list_all_variants(api_client: TestClient):
    resp = api_client.get("/api/v1/variants")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_variants_filter_by_project(api_client: TestClient):
    resp = api_client.get("/api/v1/variants", params={"project": "proj-A-exynos2500"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_variants_filter_by_severity(api_client: TestClient):
    resp = api_client.get("/api/v1/variants", params={"severity": "heavy"})
    assert resp.status_code == 200
    data = resp.json()
    assert all(v["severity"] == "heavy" for v in data["items"])
