from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

SCENARIO_ID = "uc-camera-recording"


def _valid_payload(variant_id: str = "FHD30-SDR-H265-write-test") -> dict:
    return {
        "kind": "scenario.variant_overlay",
        "actor": "codex-test",
        "note": "integration test variant overlay",
        "payload": {
            "scenario_ref": SCENARIO_ID,
            "variant": {
                "id": variant_id,
                "severity": "medium",
                "design_conditions": {
                    "resolution": "FHD",
                    "fps": 30,
                    "codec": "H.265",
                    "hdr": "SDR",
                    "concurrency": "with_preview",
                },
                "size_overrides": {
                    "record_out": "1920x1080",
                    "preview_out": "1280x720",
                },
                "routing_switch": {
                    "disabled_edges": [],
                    "disabled_nodes": [],
                },
                "node_configs": {
                    "mfc": {
                        "selected_mode": "normal",
                        "target_clock_mhz": 300,
                    }
                },
                "buffer_overrides": {
                    "RECORD_BUF": {
                        "format": "YUV420",
                        "compression": "SBWC_v4",
                        "placement": {
                            "llc_allocated": True,
                            "llc_allocation_mb": 1,
                            "llc_policy": "dedicated",
                            "allocation_owner": "MFC",
                        },
                    }
                },
                "ip_requirements": {
                    "mfc": {
                        "required_codec": "H.265",
                    }
                },
                "tags": ["write_api_test"],
            },
        },
    }


def test_variant_overlay_stage_validate_diff_apply(api_client: TestClient):
    stage = api_client.post("/api/v1/write/staging", json=_valid_payload())
    assert stage.status_code == 200
    batch_id = stage.json()["batch_id"]
    assert stage.json()["status"] == "staged"

    fetched = api_client.get(f"/api/v1/write/staging/{batch_id}")
    assert fetched.status_code == 200
    assert fetched.json()["target_id"] == f"{SCENARIO_ID}/FHD30-SDR-H265-write-test"

    validation = api_client.post(f"/api/v1/write/staging/{batch_id}/validate")
    assert validation.status_code == 200
    assert validation.json()["valid"] is True
    assert validation.json()["issues"] == []

    diff = api_client.post(f"/api/v1/write/staging/{batch_id}/diff")
    assert diff.status_code == 200
    assert diff.json()["operation"] == "create"
    changed_fields = {item["field"]: item["change"] for item in diff.json()["changes"]}
    assert changed_fields["design_conditions"] == "add"
    assert changed_fields["node_configs"] == "add"

    applied = api_client.post(f"/api/v1/write/staging/{batch_id}/apply")
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"

    variant = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/FHD30-SDR-H265-write-test")
    assert variant.status_code == 200
    body = variant.json()
    assert body["design_conditions"]["fps"] == 30
    assert body["size_overrides"]["preview_out"] == "1280x720"
    assert body["node_configs"]["mfc"]["selected_mode"] == "normal"
    assert body["buffer_overrides"]["RECORD_BUF"]["placement"]["llc_allocated"] is True


def test_variant_overlay_validation_rejects_unknown_base_route(api_client: TestClient):
    payload = _valid_payload("invalid-route-write-test")
    payload["payload"]["variant"]["routing_switch"] = {
        "disabled_edges": [{"from": "isp0", "to": "npu0"}],
    }
    stage = api_client.post("/api/v1/write/staging", json=payload)
    assert stage.status_code == 200
    batch_id = stage.json()["batch_id"]

    validation = api_client.post(f"/api/v1/write/staging/{batch_id}/validate")
    assert validation.status_code == 200
    body = validation.json()
    assert body["valid"] is False
    assert any(issue["code"] == "unknown_disabled_edge" for issue in body["issues"])

    diff = api_client.post(f"/api/v1/write/staging/{batch_id}/diff")
    assert diff.status_code == 409


def test_variant_overlay_validation_rejects_hw_topology_injection(api_client: TestClient):
    payload = _valid_payload("invalid-hw-injection-write-test")
    payload["payload"]["variant"]["topology_patch"] = {
        "add_nodes": [
            {"id": "npu0", "node_type": "HW", "ip_ref": "ip-npu-v1"},
        ],
        "add_edges": [
            {"from": "isp0", "to": "npu0", "type": "M2M"},
        ],
    }
    stage = api_client.post("/api/v1/write/staging", json=payload)
    assert stage.status_code == 200
    batch_id = stage.json()["batch_id"]

    validation = api_client.post(f"/api/v1/write/staging/{batch_id}/validate")
    assert validation.status_code == 200
    body = validation.json()
    assert body["valid"] is False
    assert any(issue["code"] == "hw_node_injection_forbidden" for issue in body["issues"])


def test_variant_overlay_validation_rejects_unsupported_selected_mode(api_client: TestClient):
    payload = _valid_payload("invalid-mode-write-test")
    payload["payload"]["variant"]["node_configs"]["mfc"]["selected_mode"] = "low_power"
    stage = api_client.post("/api/v1/write/staging", json=payload)
    assert stage.status_code == 200
    batch_id = stage.json()["batch_id"]

    validation = api_client.post(f"/api/v1/write/staging/{batch_id}/validate")
    assert validation.status_code == 200
    body = validation.json()
    assert body["valid"] is False
    assert any(issue["code"] == "unsupported_selected_mode" for issue in body["issues"])
