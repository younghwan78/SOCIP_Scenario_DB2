from __future__ import annotations

from types import SimpleNamespace
from copy import deepcopy

import pytest

from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    NodeData,
    NodeElement,
    ResourceOverviewRow,
    ViewResponse,
    ViewSummary,
)
from scenario_db.view.service import apply_simulation_overlay


def test_apply_simulation_overlay_adds_node_and_edge_details():
    view = ViewResponse(
        level=0,
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        mode="topology",
        nodes=[
            NodeElement(
                data=NodeData(
                    id="isp0",
                    label="ISP",
                    type="ip",
                    layer="hw",
                    ip_ref="ip-isp-v12",
                ),
                position={"x": 0, "y": 0},
            )
        ],
        edges=[
            EdgeElement(
                data=EdgeData(
                    id="e-isp0-mfc",
                    source="isp0",
                    target="mfc",
                    flow_type="M2M",
                )
            )
        ],
        summary=ViewSummary(
            scenario_id="uc-camera-recording",
            variant_id="FHD30-SDR-H265",
            name="Camera",
            subtitle="FHD30",
            period_ms=33.3,
            budget_ms=30.0,
            resolution="1920x1080",
            fps=30,
            variant_label="FHD30",
        ),
        level0_resource_overview=Level0ResourceOverview(
            rows=[
                ResourceOverviewRow(
                    sequence_index=1,
                    node_id="isp0",
                    label="ISP",
                    resource_domain="soc_resource",
                    resource_kind="isp",
                    subsystem="camera",
                    flow="M2M",
                    buffer_refs=["YUV_BUF"],
                )
            ],
            metric_breakdown=[Level0MetricBreakdown(subsystem="camera", node_count=1)],
        ),
    )
    evidence = SimpleNamespace(
        id="sim-test-01",
        dvfs_breakdown=[
            {
                "node_id": "isp0",
                "ip_ref": "ip-isp-v12",
                "hw_name": "ISP",
                "required_clock_mhz": 200,
                "set_clock_mhz": 400,
                "set_voltage_mv": 700,
                "total_power_mw": 12.5,
                "feasible": True,
            }
        ],
        timing_breakdown=[
            {"node_id": "isp0", "hw_time_ms": 1.2, "feasible": True}
        ],
        dma_breakdown=[
            {
                "node_id": "isp0",
                "hw_name": "ISP",
                "port": "WDMA_BE",
                "bw_mbs": 46.6,
                "bw_power_mw": 3.7,
            }
        ],
    )

    result = apply_simulation_overlay(view, evidence)

    node = result.nodes[0].data
    edge = result.edges[0].data
    assert node.sim_overlay is not None
    assert node.sim_overlay.set_clock_mhz == 400
    assert "400MHz" in node.summary_badges
    assert any(item.startswith("Sim:") for item in node.detail_items)
    assert edge.sim_overlay is not None
    assert edge.sim_overlay.bw_mbs == 46.6
    assert result.level0_resource_overview is not None
    resource_row = result.level0_resource_overview.rows[0]
    assert resource_row.metrics is not None
    assert resource_row.metrics.power_mw == 12.5
    assert resource_row.metrics.bw_total_mbs == 46.6
    assert resource_row.metrics.hw_time_ms == 1.2
    assert result.level0_resource_overview.metric_breakdown[0].power_mw == 12.5
    assert result.level0_resource_overview.metric_breakdown[0].bw_total_mbs == 46.6
    assert "simulation" in result.overlays_available
    assert result.metadata["simulation_evidence_id"] == "sim-test-01"


def test_apply_simulation_overlay_does_not_attach_unmatched_dma_to_all_m2m_edges():
    view = ViewResponse(
        level=0,
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        mode="topology",
        nodes=[],
        edges=[
            EdgeElement(
                data=EdgeData(
                    id="e-display-path",
                    source="dpu",
                    target="panel",
                    flow_type="M2M",
                    buffer_ref="DISPLAY_BUF",
                )
            )
        ],
        summary=ViewSummary(
            scenario_id="uc-camera-recording",
            variant_id="FHD30-SDR-H265",
            name="Camera",
            subtitle="FHD30",
            period_ms=33.3,
            budget_ms=30.0,
            resolution="1920x1080",
            fps=30,
            variant_label="FHD30",
        ),
    )
    evidence = SimpleNamespace(
        id="sim-test-02",
        dvfs_breakdown=[],
        timing_breakdown=[],
        dma_breakdown=[
            {
                "node_id": "isp0",
                "hw_name": "ISP",
                "bw_mbs": 46.6,
                "bw_power_mw": 3.7,
            }
        ],
    )

    result = apply_simulation_overlay(view, evidence)

    assert result.edges[0].data.sim_overlay is None


def _summary() -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd30-vdis",
        name="Camera",
        subtitle="FHD30",
        period_ms=33.3,
        budget_ms=30.0,
        resolution="1920x1080",
        fps=30,
        variant_label="FHD30",
    )


def _hw_node(node_id: str) -> NodeElement:
    return NodeElement(
        data=NodeData(id=node_id, label=node_id.upper(), type="ip", layer="hw"),
        position={"x": 0, "y": 0},
    )


def test_apply_simulation_overlay_maps_timeline_schedule_and_critical_path():
    view = ViewResponse(
        level=1,
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd30-vdis",
        mode="architecture",
        nodes=[_hw_node("ip-csispdp"), _hw_node("ip-mcsc"), _hw_node("ip-dpu")],
        edges=[
            EdgeElement(data=EdgeData(id="e-a", source="ip-csispdp", target="ip-mcsc", flow_type="OTF")),
            EdgeElement(data=EdgeData(id="e-b", source="ip-mcsc", target="ip-dpu", flow_type="M2M")),
        ],
        summary=_summary(),
    )
    evidence = SimpleNamespace(
        id="sim-test-03",
        dvfs_breakdown=[],
        timing_breakdown=[],
        dma_breakdown=[],
        timeline_events=[
            {
                "node_id": "csispdp",
                "task_id": "csispdp#f0",
                "critical_path_rank": 0,
                "predecessors": [],
                "frame_index": 0,
                "start_ms": 0.0,
                "end_ms": 18.9,
                "critical": True,
                "bottleneck": True,
            },
            {
                "node_id": "mcsc",
                "frame_index": 0,
                "task_id": "mcsc#f0",
                "critical_path_rank": 1,
                "predecessors": ["csispdp#f0"],
                "start_ms": 18.9,
                "end_ms": 26.4,
                "critical": True,
            },
            # Later frame only marks flags; frame-0 window must stay authoritative.
            {
                "node_id": "mcsc",
                "frame_index": 1,
                "start_ms": 52.2,
                "end_ms": 59.7,
            },
            {
                "node_id": "dpu",
                "frame_index": 0,
                "start_ms": 26.4,
                "end_ms": 29.7,
            },
        ],
    )

    result = apply_simulation_overlay(view, evidence)

    csis = result.nodes[0].data
    mcsc = result.nodes[1].data
    dpu = result.nodes[2].data
    assert csis.sim_overlay is not None and csis.sim_overlay.critical
    assert csis.sim_overlay.bottleneck
    assert "CRIT" in csis.summary_badges
    assert mcsc.sim_overlay is not None
    assert (mcsc.sim_overlay.start_ms, mcsc.sim_overlay.end_ms) == (18.9, 26.4)
    assert any("t 18.90-26.40ms" in item for item in mcsc.detail_items)
    assert dpu.sim_overlay is not None and not dpu.sim_overlay.critical
    # Edge between two critical nodes is flagged; the one into dpu is not.
    assert result.edges[0].data.critical is True
    assert not result.edges[1].data.critical


def _schedule_view():
    return ViewResponse(
        level=1, scenario_id="uc-camera-recording", variant_id="cam-rec-r1-fhd30-vdis",
        nodes=[_hw_node("ip-a"), _hw_node("ip-b"), _hw_node("ip-c"), _hw_node("ip-display")],
        edges=[EdgeElement(data=EdgeData(id=f"{a}-{b}", source=f"ip-{a}", target=f"ip-{b}", flow_type="M2M"))
               for a, b in [("a", "b"), ("b", "c"), ("a", "c")]],
        summary=_summary(),
    )


def _schedule_evidence(events):
    return SimpleNamespace(id="sim-schedule", dvfs_breakdown=[], timing_breakdown=[], dma_breakdown=[], timeline_events=events)


def test_schedule_matches_only_unique_node_identity_and_preserves_frame_zero():
    from scenario_db.view.simulation_overlay import _match_node_schedule, _sim_schedule_rows

    rows = _sim_schedule_rows(_schedule_evidence([
        {"node_id": "isp", "frame_index": 1, "start_ms": 40, "end_ms": 50, "critical": True},
        {"node_id": "isp", "frame_index": 0, "start_ms": 5, "end_ms": 9},
        {"node_id": "isp", "frame_index": 0, "start_ms": 0, "end_ms": 4},
        {"task_id": "gdc_m#f0", "start_ms": 1, "end_ms": 2},
    ]))
    assert _match_node_schedule(_hw_node("ip-display").data, rows) is None
    match = _match_node_schedule(_hw_node("ip-isp").data, rows)
    assert (match["start_ms"], match["end_ms"], match["critical"]) == (0, 9, True)
    assert _match_node_schedule(_hw_node("ip-gdc-m").data, rows)["start_ms"] == 1
    rows["gdc-m"] = {"start_ms": 100, "end_ms": 200}
    assert _match_node_schedule(_hw_node("ip-gdc-m").data, rows) is None


def test_scheduler_proves_only_consecutive_dependency_edges_critical():
    from scenario_db.sim.timeline import build_timeline_events

    events = build_timeline_events(
        [{"id": name, "node_id": name, "duration_ms": 5, "resource_id": name} for name in ("a", "b", "c")],
        [{"from": "a", "to": "b", "type": "M2M"}, {"from": "b", "to": "c", "type": "M2M"},
         {"from": "a", "to": "c", "type": "M2M"}],
    )
    view = apply_simulation_overlay(_schedule_view(), _schedule_evidence([event.model_dump() for event in events]))
    assert [edge.data.critical for edge in view.edges] == [True, True, False]


@pytest.mark.parametrize("mutation", [
    {"predecessors": []}, {"predecessors": "a#f0"}, {"critical_path_rank": None},
    {"critical_path_rank": 3}, {"frame_index": 1}, {"critical": False},
    {"critical_path_rank": True},
])
def test_critical_edge_rejects_missing_or_unrelated_path_evidence(mutation):
    source = {"task_id": "a#f0", "node_id": "a", "frame_index": 0, "critical": True, "critical_path_rank": 0}
    target = {"task_id": "b#f0", "node_id": "b", "frame_index": 0, "critical": True,
              "critical_path_rank": 1, "predecessors": ["a#f0"], **mutation}
    view = apply_simulation_overlay(_schedule_view(), _schedule_evidence([source, target]))
    assert view.edges[0].data.critical is False


def test_critical_edges_reset_and_duplicate_task_ids_are_ambiguous():
    from scenario_db.view.simulation_overlay import _mark_critical_edges

    source = {"task_id": "a#f0", "node_id": "a", "critical": True, "critical_path_rank": 0}
    target = {"task_id": "b#f0", "node_id": "b", "critical": True, "critical_path_rank": 1, "predecessors": ["a#f0"]}
    view = _schedule_view()
    _mark_critical_edges(view, [source, target])
    assert view.edges[0].data.critical is True
    _mark_critical_edges(view, [source, target, deepcopy(source)])
    assert not any(edge.data.critical for edge in view.edges)
    _mark_critical_edges(view, [])
    assert not any(edge.data.critical for edge in view.edges)


def test_schedule_with_only_later_frames_does_not_invent_frame_zero_window():
    view = apply_simulation_overlay(_schedule_view(), _schedule_evidence([
        {"node_id": "a", "frame_index": 2, "start_ms": 100, "end_ms": 110, "critical": True},
    ]))
    overlay = view.nodes[0].data.sim_overlay
    assert overlay.critical is True
    assert overlay.start_ms is None and overlay.end_ms is None
