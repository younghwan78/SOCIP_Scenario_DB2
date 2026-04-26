"""Evidence 레이어 API — 실 DB 검증 (summary groupby 포함)."""
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

EVIDENCE_ID = "sim-uc-camera-recording-UHD60-HDR10-H265-A0-sw123-20260419"
VARIANT_REF = "UHD60-HDR10-H265"
SW_VERSION = "sw-vendor-v1.2.3"


def test_list_evidence(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_get_evidence_by_id(api_client: TestClient):
    resp = api_client.get(f"/api/v1/evidence/{EVIDENCE_ID}")
    assert resp.status_code == 200
    assert resp.json()["id"] == EVIDENCE_ID


def test_evidence_404(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence/no-such-evidence")
    assert resp.status_code == 404


def test_evidence_sw_version_filter(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence", params={"sw_version": SW_VERSION})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(e["sw_version_hint"] == SW_VERSION for e in data["items"])


def test_evidence_variant_filter(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence", params={"variant_ref": VARIANT_REF})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_evidence_summary_groupby_sw_version(api_client: TestClient):
    """실 DB groupby — sw_version_hint별 count 반환."""
    resp = api_client.get("/api/v1/evidence/summary", params={"groupby": "sw_version_hint"})
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    for row in rows:
        assert "sw_version_hint" in row
        assert "count" in row
        assert row["count"] >= 1


def test_evidence_summary_groupby_feasibility(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence/summary", params={"groupby": "overall_feasibility"})
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1


def test_evidence_summary_invalid_column_400(api_client: TestClient):
    resp = api_client.get("/api/v1/evidence/summary", params={"groupby": "bad_column"})
    assert resp.status_code == 400


def test_compare_evidence(api_client: TestClient):
    """두 SW 버전 Evidence KPI 비교."""
    resp = api_client.get(
        "/api/v1/compare/evidence",
        params={
            "variant": VARIANT_REF,
            "sw1": "sw-vendor-v1.2.3",
            "sw2": "sw-vendor-v1.3.0",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "sw-vendor-v1.2.3" in data
    assert "sw-vendor-v1.3.0" in data


def test_compare_variants(api_client: TestClient):
    """두 variant의 최신 Evidence 비교."""
    resp = api_client.get(
        "/api/v1/compare/variants",
        params={
            "ref1": f"uc-camera-recording::{VARIANT_REF}",
            "ref2": "uc-camera-recording::8K120-HDR10plus-AV1-exploration",
        },
    )
    assert resp.status_code == 200
