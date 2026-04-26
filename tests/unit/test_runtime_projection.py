from __future__ import annotations

from types import SimpleNamespace

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.resolver.models import ResolverResult
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.view.service import _project_topology


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
