from __future__ import annotations

from types import SimpleNamespace

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
