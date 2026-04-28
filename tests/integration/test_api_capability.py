"""Capability 레이어 API — 실 PostgreSQL 검증 (JSONB 필터 포함)."""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# SoC Platforms
# ---------------------------------------------------------------------------

def test_soc_platforms_returns_data(api_client: TestClient):
    resp = api_client.get("/api/v1/soc-platforms")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(p["id"] == "soc-exynos2500" for p in data["items"])


def test_get_soc_platform_by_id(api_client: TestClient):
    resp = api_client.get("/api/v1/soc-platforms/soc-exynos2500")
    assert resp.status_code == 200
    assert resp.json()["id"] == "soc-exynos2500"


def test_soc_platform_404(api_client: TestClient):
    resp = api_client.get("/api/v1/soc-platforms/no-such-soc")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# IP Catalog
# ---------------------------------------------------------------------------

def test_ip_catalog_returns_data(api_client: TestClient):
    resp = api_client.get("/api/v1/ip-catalogs")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_ip_catalog_category_filter_valid_returns_200(api_client: TestClient):
    """whitelist에 포함된 category 필터는 항상 200 반환 (결과 0개도 유효)."""
    resp = api_client.get("/api/v1/ip-catalogs", params={"category": "ISP"})
    assert resp.status_code == 200
    data = resp.json()
    # demo 픽스처의 IP category 값은 'camera'/'codec'/'memory'/'display' 등 소문자 사용 →
    # whitelist(ISP/MFC/DPU/GPU/LLC)와 불일치하여 0건이 정상
    assert isinstance(data["total"], int)


@pytest.mark.parametrize("category, expected_id", [
    ("sensor", "ip-sensor-hp2-projectA"),
    ("display", "ip-display-fhd-panel-projectA"),
])
def test_ip_catalog_external_category_filters(api_client: TestClient, category: str, expected_id: str):
    resp = api_client.get("/api/v1/ip-catalogs", params={"category": category})
    assert resp.status_code == 200
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert expected_id in ids


def test_ip_catalog_invalid_category_400(api_client: TestClient):
    resp = api_client.get("/api/v1/ip-catalogs", params={"category": "INVALID_CAT"})
    assert resp.status_code == 400


def test_get_ip_by_id(api_client: TestClient):
    resp = api_client.get("/api/v1/ip-catalogs/ip-isp-v12")
    assert resp.status_code == 200
    assert resp.json()["id"] == "ip-isp-v12"


# ---------------------------------------------------------------------------
# SW Profiles (JSONB feature_flags 필터)
# ---------------------------------------------------------------------------

def test_sw_profiles_returns_data(api_client: TestClient):
    resp = api_client.get("/api/v1/sw-profiles")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_sw_profiles_feature_flag_filter(api_client: TestClient):
    """LLC_per_ip_partition:disabled 필터 — sw-vendor-v1.2.3 반환."""
    resp = api_client.get(
        "/api/v1/sw-profiles",
        params={"feature_flag": "LLC_per_ip_partition:disabled"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    ids = [p["id"] for p in data["items"]]
    assert "sw-vendor-v1.2.3" in ids


def test_sw_profiles_feature_flag_enabled_filter(api_client: TestClient):
    """LLC_dynamic_allocation:enabled 필터."""
    resp = api_client.get(
        "/api/v1/sw-profiles",
        params={"feature_flag": "LLC_dynamic_allocation:enabled"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_sw_profiles_invalid_flag_400(api_client: TestClient):
    """화이트리스트 미포함 feature_flag → 400."""
    resp = api_client.get(
        "/api/v1/sw-profiles",
        params={"feature_flag": "INJECTION_ATTACK:true"},
    )
    assert resp.status_code == 400


def test_sw_profiles_malformed_flag_400(api_client: TestClient):
    """':' 없는 feature_flag → 400."""
    resp = api_client.get(
        "/api/v1/sw-profiles",
        params={"feature_flag": "LLC_per_ip_partition"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# SW Components
# ---------------------------------------------------------------------------

def test_sw_components_returns_data(api_client: TestClient):
    resp = api_client.get("/api/v1/sw-components")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
