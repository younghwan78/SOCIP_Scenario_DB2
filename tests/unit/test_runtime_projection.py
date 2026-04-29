from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.resolver.models import ResolverResult
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.view.service import _project_architecture, _project_reference_level1, _project_topology


def _graph() -> CanonicalScenarioGraph:
    scenario = SimpleNamespace(
        id="uc-camera-recording",
        project_ref="proj-A-exynos2500",
        metadata_={"name": "Camera Recording Pipeline"},
        pipeline={
            "nodes": [
                {"id": "csis0", "ip_ref": "ip-csis-v8"},
                {"id": "isp0", "ip_ref": "ip-isp-v12"},
                {"id": "mfc", "ip_ref": "ip-mfc-v14"},
            ],
            "edges": [
                {"from": "csis0", "to": "isp0", "type": "OTF"},
                {"from": "isp0", "to": "mfc", "type": "M2M", "buffer": "RECORD_BUF"},
            ],
        },
        size_profile={"anchors": {"sensor_full": "4000x3000", "record_out": "3840x2160"}},
    )
    variant = SimpleNamespace(
        id="UHD60-HDR10-H265",
        severity="heavy",
        design_conditions={
            "resolution": "UHD",
            "fps": 60,
            "codec": "H.265",
            "hdr": "HDR10",
        },
        ip_requirements={"llc": {"required_allocations": {"MFC": "1MB"}}},
        sw_requirements={
            "required_features": [
                {"LLC_dynamic_allocation": "enabled"},
                {"LLC_per_ip_partition": "enabled"},
            ]
        },
    )
    evidence = SimpleNamespace(
        id="sim-UHD60-A0-sw123",
        execution_context={
            "silicon_rev": "A0",
            "thermal": "hot",
            "power_state": "charging",
            "sw_baseline_ref": "sw-vendor-v1.2.3",
        },
        resolution_result={
            "overall_feasibility": "exploration_only",
            "sw_resolution": {
                "required_features_check": [
                    {
                        "feature": "LLC_per_ip_partition",
                        "actual": "disabled",
                        "status": "FAIL",
                    }
                ],
                "violations": [{"feature": "LLC_per_ip_partition"}],
            },
        },
        kpi={},
        ip_breakdown=[],
    )
    issue = SimpleNamespace(
        id="iss-LLC-thrashing-0221",
        metadata_={"title": "LLC thrashing", "severity": "heavy", "status": "resolved"},
        affects=[
            {
                "scenario_ref": "uc-camera-recording",
                "match_rule": {
                    "all": [
                        {"axis": "resolution", "op": "eq", "value": "UHD"},
                        {"axis": "thermal", "op": "eq", "value": "hot"},
                    ],
                    "any": [
                        {"sw_feature": "LLC_per_ip_partition", "op": "eq", "value": "disabled"},
                    ],
                    "none": [
                        {"axis": "power_state", "op": "eq", "value": "battery"},
                    ],
                },
            }
        ],
        affects_ip=[{"ip_ref": "ip-isp-v12", "submodule": "ISP.TNR"}],
    )
    waiver = SimpleNamespace(
        id="waiver-LLC-thrashing",
        issue_ref="iss-LLC-thrashing-0221",
        status="approved",
        scope={
            "variant_scope": {
                "scenario_ref": "uc-camera-recording",
                "match_rule": {
                    "all": [
                        {"axis": "resolution", "op": "eq", "value": "UHD"},
                        {"axis": "fps", "op": "eq", "value": 60},
                    ]
                },
            },
            "execution_scope": {
                "all": [
                    {"axis": "silicon_rev", "op": "eq", "value": "A0"},
                    {"axis": "thermal", "op": "eq", "value": "hot"},
                ]
            },
        },
    )
    gate_rule = SimpleNamespace(
        id="rule-known-issue-match",
        metadata_={"name": "Known Issue Match Check"},
        applies_to={"match": {"variant.severity": {"$in": ["heavy", "critical"]}}},
        condition={
            "match": {
                "evidence.resolution_result.sw_resolution.violations": {"$not_empty": True}
            }
        },
        action={"gate_result": "WARN", "message_template": "Known issue detected."},
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        soc=SimpleNamespace(id="soc-exynos2500"),
        ip_catalog={
            "ip-csis-v8": SimpleNamespace(category="camera", capabilities={}, hierarchy={}),
            "ip-isp-v12": SimpleNamespace(
                category="camera",
                capabilities={"supported_features": {"hdr_formats": ["HDR10"], "compression": ["SBWC_v4"], "bitdepth": [8, 10]}},
                hierarchy={},
            ),
            "ip-mfc-v14": SimpleNamespace(category="codec", capabilities={}, hierarchy={}),
        },
        evidence=[evidence],
        issues=[issue],
        waivers=[waiver],
        gate_rules=[gate_rule],
    )


def test_review_gate_matches_issue_and_approved_waiver():
    graph = _graph()
    result = run_review_gate(
        graph,
        ResolverResult(scenario_id=graph.scenario_id, variant_id=graph.variant_id),
    )

    assert result.status == "WARN"
    assert [issue.issue_id for issue in result.matched_issues] == ["iss-LLC-thrashing-0221"]
    assert result.applicable_waivers[0].applies is True
    assert result.missing_waivers == []


def test_topology_projection_contains_vertical_buffer_and_llc_metadata():
    view = _project_topology(_graph(), level=0)

    assert view.mode == "topology"
    assert any(node.data.id == "buf-record-buf" for node in view.nodes)
    buffer_node = next(node for node in view.nodes if node.data.id == "buf-record-buf")
    assert buffer_node.data.memory.format == "NV12"
    assert buffer_node.data.placement.llc_allocated is True
    assert any(edge.data.buffer_ref == "RECORD_BUF" for edge in view.edges)


def _imported_variant_graph() -> CanonicalScenarioGraph:
    scenario = SimpleNamespace(
        id="uc-imported-camera-recording",
        project_ref="proj-projectA",
        metadata_={"name": "Imported Camera Recording"},
        pipeline={
            "nodes": [
                {"id": "t_csis", "ip_ref": "ip-csis-v8", "role": "sensor"},
                {"id": "t_postIRTA", "ip_ref": "ip-cpu-mid", "node_type": "sw", "role": "sw_task"},
                {"id": "t_mfc", "ip_ref": "ip-mfc-v14", "role": "codec"},
                {"id": "t_dpu", "ip_ref": "ip-dpu-v9", "role": "display"},
            ],
            "edges": [
                {"from": "t_csis", "to": "t_postIRTA", "type": "control"},
                {"from": "t_postIRTA", "to": "t_mfc", "type": "M2M", "buffer": "RECORD_BUF"},
                {"from": "t_postIRTA", "to": "t_dpu", "type": "M2M", "buffer": "PREVIEW_BUF"},
            ],
            "buffers": {
                "RECORD_BUF": {
                    "format": "NV12",
                    "bitdepth": 8,
                    "size_ref": "record",
                    "alignment": "64B",
                },
                "PREVIEW_BUF": {
                    "format": "NV12",
                    "bitdepth": 8,
                    "size_ref": "preview",
                    "alignment": "64B",
                },
            },
            "task_graph": {
                "layout": "task-topology",
                "nodes": [
                    {"id": "t_csis", "label": "CSIS", "layer": "hw", "x": 500, "y": 100},
                    {"id": "t_postIRTA", "label": "postIRTA", "layer": "kernel", "x": 500, "y": 230},
                    {"id": "t_mfc", "label": "MFC", "layer": "hw", "x": 420, "y": 360, "buffer": "RECORD_BUF"},
                    {"id": "t_dpu", "label": "DPU", "layer": "hw", "x": 610, "y": 360, "buffer": "PREVIEW_BUF"},
                ],
                "edges": [
                    {"from": "t_csis", "to": "t_postIRTA", "type": "SW"},
                    {"from": "t_postIRTA", "to": "t_mfc", "type": "M2M", "buffer": "RECORD_BUF"},
                    {"from": "t_postIRTA", "to": "t_dpu", "type": "M2M", "buffer": "PREVIEW_BUF"},
                ],
            },
            "level1_graph": {
                "nodes_from_task_graph": True,
                "groups": [{"id": "grp-imported", "label": "Imported Path", "x": 520, "y": 260, "width": 520, "height": 420}],
            },
        },
        size_profile={"anchors": {"sensor_full": "4000x2252", "record_out": "1920x1080", "preview_out": "1280x720"}},
    )
    variant = SimpleNamespace(
        id="FHD30-Recording-NoDisplay",
        severity="medium",
        design_conditions={"resolution": "FHD", "fps": 30, "codec": "H.265"},
        size_overrides={"record_out": "1920x1080", "preview_out": "1280x720"},
        routing_switch={
            "disabled_nodes": ["t_dpu"],
            "disabled_edges": [{"from": "t_postIRTA", "to": "t_dpu", "buffer": "PREVIEW_BUF"}],
        },
        topology_patch={},
        node_configs={
            "t_postIRTA": {
                "kind": "sw_task",
                "name": "postIRTA",
                "processor": "CPU_MID_Cluster",
                "duration_ms": 4.0,
            },
            "t_mfc": {
                "kind": "ip",
                "mode": "Normal",
                "inputs": [{"port": "MFC_RDMA", "size": [0, 0, 1920, 1080], "format": "YUV420", "bitwidth": 10}],
            },
        },
        buffer_overrides={
            "RECORD_BUF": {
                "format": "YUV420",
                "bitdepth": 10,
                "compression": "SBWC_v4",
                "placement": {
                    "llc_allocated": True,
                    "llc_allocation_mb": 1.0,
                    "llc_policy": "dedicated",
                    "allocation_owner": "MFC",
                },
            }
        },
        ip_requirements={},
        sw_requirements={},
        resolved=True,
        inheritance_chain=["FHD30-Recording-NoDisplay"],
    )
    return CanonicalScenarioGraph(
        scenario=scenario,
        variant=variant,
        soc=SimpleNamespace(id="soc-projectA"),
        ip_catalog={
            "ip-csis-v8": SimpleNamespace(category="camera", capabilities={}, hierarchy={}),
            "ip-cpu-mid": SimpleNamespace(category="cpu", capabilities={}, hierarchy={}),
            "ip-mfc-v14": SimpleNamespace(category="codec", capabilities={}, hierarchy={}),
            "ip-dpu-v9": SimpleNamespace(category="display", capabilities={}, hierarchy={}),
        },
    )


def test_imported_variant_routing_switch_hides_disabled_branch_in_view_projections():
    graph = _imported_variant_graph()

    architecture = _project_architecture(graph, level=0)
    topology = _project_topology(graph, level=0)
    level1 = _project_reference_level1(graph)

    for view in (architecture, topology, level1):
        node_ids = {node.data.id for node in view.nodes}
        assert "ip-t_dpu" not in node_ids
        assert "t_dpu" not in node_ids
        assert all(edge.data.target not in {"ip-t_dpu", "t_dpu"} for edge in view.edges)
        assert view.metadata["variant_overlay"]["disabled_nodes"] == ["t_dpu"]


def test_imported_variant_detail_payload_exposes_node_config_buffer_override_and_llc():
    graph = _imported_variant_graph()
    view = _project_reference_level1(graph)

    sw_node = next(node for node in view.nodes if node.data.id == "t_postIRTA")
    assert any("SW task" in item for item in sw_node.data.detail_items)
    assert any("CPU_MID_Cluster" in item for item in sw_node.data.detail_items)

    mfc_node = next(node for node in view.nodes if node.data.id == "t_mfc")
    assert any("Inputs:" in item and "MFC_RDMA" in item for item in mfc_node.data.detail_items)
    assert any("Buffer override" in item for item in mfc_node.data.detail_items)
    assert mfc_node.data.placement.llc_allocated is True

    m2m_edge = next(edge for edge in view.edges if edge.data.buffer_ref == "RECORD_BUF")
    assert any("Buffer override" in item for item in m2m_edge.data.detail_items)
    assert m2m_edge.data.placement.llc_allocated is True
    assert view.metadata["variant_overlay"]["node_config_count"] == 2
    assert view.metadata["variant_overlay"]["buffer_override_count"] == 1
    assert view.metadata["variant_overlay"]["sw_task_count"] == 1
