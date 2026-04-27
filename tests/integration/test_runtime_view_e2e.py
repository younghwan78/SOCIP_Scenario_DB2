from __future__ import annotations


SCENARIO_ID = "uc-camera-recording"
VARIANT_ID = "UHD60-HDR10-H265"
DERIVED_VARIANT_ID = "UHD60-HDR10-sustained-10min"


def test_runtime_graph_summary_e2e(api_client):
    response = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == SCENARIO_ID
    assert body["variant_id"] == VARIANT_ID
    assert body["node_count"] >= 4
    assert "ip-isp-v12" in body["ip_refs"]
    assert body["evidence_refs"]


def test_runtime_resolver_e2e(api_client):
    response = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/resolve")

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == SCENARIO_ID
    assert body["variant_id"] == VARIANT_ID
    assert "isp0" in body["ip_resolutions"]
    assert body["ip_resolutions"]["isp0"]["status"] == "PASS"


def test_runtime_resolver_uses_resolved_derived_variant(api_client):
    response = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/{DERIVED_VARIANT_ID}/resolve")

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == SCENARIO_ID
    assert body["variant_id"] == DERIVED_VARIANT_ID
    assert "mfc" in body["ip_resolutions"]
    assert body["ip_resolutions"]["mfc"]["requested"]["required_codec"] == "H.265"


def test_runtime_review_gate_e2e(api_client):
    response = api_client.get(f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/gate")

    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == SCENARIO_ID
    assert body["variant_id"] == VARIANT_ID
    assert body["status"] in {"PASS", "WARN", "BLOCK", "WAIVER_REQUIRED"}
    assert body["matched_rules"]
    assert body["evidence_refs"]


def test_view_architecture_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 0, "mode": "architecture"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "architecture"
    assert body["level"] == 0
    assert body["summary"]["scenario_id"] == SCENARIO_ID
    assert body["summary"]["variant_id"] == VARIANT_ID
    assert {"nodes", "edges", "risks", "metadata", "overlays_available"}.issubset(body)
    assert any(node["data"]["layer"] == "hw" for node in body["nodes"])
    assert any(node["data"]["layer"] == "memory" for node in body["nodes"])
    assert any(edge["data"]["flow_type"] == "M2M" for edge in body["edges"])
    assert "llc-allocation" in body["overlays_available"]


def test_view_summary_uses_resolved_derived_variant(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{DERIVED_VARIANT_ID}/view",
        params={"level": 0, "mode": "architecture"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["variant_id"] == DERIVED_VARIANT_ID
    assert body["summary"]["fps"] == 60
    assert body["summary"]["resolution"] == "3840 x 2160"
    assert any(
        (node["data"].get("memory") or {}).get("width") == 3840
        for node in body["nodes"]
        if node["data"]["type"] == "buffer"
    )


def test_view_topology_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 0, "mode": "topology"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "topology"
    assert body["metadata"]["layout"] == "vertical-topology"
    assert any(node["data"]["id"] == "t_csis" for node in body["nodes"])
    assert not any(node["data"]["type"] == "buffer" for node in body["nodes"])


def test_view_drilldown_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 2, "expand": "isp0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == 2
    assert body["metadata"]["expand"] == "isp0"
    assert any(node["data"]["type"] == "submodule" for node in body["nodes"])
    assert any(node["data"]["type"] == "dma_group" for node in body["nodes"])
    assert any(node["data"]["type"] == "sysmmu" for node in body["nodes"])


def test_view_level1_projection_contract_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["level"] == 1
    assert body["metadata"]["layout"] == "level1-reference"
    assert any(node["data"]["id"] == "grp-isp" for node in body["nodes"])
    assert any(node["data"]["active_operations"] for node in body["nodes"])
    assert any(edge["data"]["memory"] for edge in body["edges"] if edge["data"]["flow_type"] == "M2M")


def test_view_level2_requires_expand_error_contract(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 2},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": "validation_error",
        "detail": "expand= required for level=2",
    }


def test_view_unknown_scenario_error_contract(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/unknown-scenario/variants/{VARIANT_ID}/view",
        params={"level": 0, "mode": "architecture"},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "not_found"
    assert "Scenario not found" in body["detail"]


def test_view_level2_camera_reference_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 2, "expand": "camera"},
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["data"]["id"] for node in body["nodes"]}
    node_types = {node["data"]["type"] for node in body["nodes"]}
    assert body["metadata"]["expand"] == "camera"
    assert body["metadata"]["layout"] == "level2-camera-detail"
    assert "l2cam-csis" in node_ids
    assert "l2cam-mlsc" in node_ids
    assert "l2cam-sysmmu" in node_ids
    assert {"sw", "submodule", "dma_channel", "sysmmu", "buffer"}.issubset(node_types)


def test_view_level2_video_reference_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 2, "expand": "video"},
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["data"]["id"] for node in body["nodes"]}
    assert body["metadata"]["expand"] == "video"
    assert body["metadata"]["layout"] == "level2-video-detail"
    assert "l2vid-mfc" in node_ids
    assert "l2vid-sysmmu" in node_ids
    assert any(node["data"]["type"] == "sw" for node in body["nodes"])
    assert any(node["data"]["type"] == "dma_channel" for node in body["nodes"])


def test_view_level2_display_reference_projection_e2e(api_client):
    response = api_client.get(
        f"/api/v1/scenarios/{SCENARIO_ID}/variants/{VARIANT_ID}/view",
        params={"level": 2, "expand": "display"},
    )

    assert response.status_code == 200
    body = response.json()
    node_ids = {node["data"]["id"] for node in body["nodes"]}
    assert body["metadata"]["expand"] == "display"
    assert body["metadata"]["layout"] == "level2-display-detail"
    assert "l2disp-dpu" in node_ids
    assert "l2disp-sysmmu" in node_ids
    assert any(node["data"]["type"] == "sw" for node in body["nodes"])
