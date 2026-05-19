from __future__ import annotations

from dashboard.components.graph_inspector import (
    build_edge_inspector,
    build_graph_overview,
    build_node_inspector,
    edge_options,
    inspector_heading_html,
    inspector_view_source,
    node_options,
)
from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    EdgeSimOverlay,
    MemoryDescriptor,
    MemoryPlacement,
    NodeData,
    NodeElement,
    OperationSummary,
    RiskCard,
    SimOverlay,
    ViewResponse,
    ViewSummary,
)


def _summary(*, name: str = "Camera Recording", resolution: str = "1920 x 1080") -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        name=name,
        subtitle="FHD 30fps",
        period_ms=33.33,
        budget_ms=30.0,
        resolution=resolution,
        fps=30,
        variant_label="soc-exynos2600",
    )


def _node(node_id: str, label: str, node_type: str, layer: str, **kwargs) -> NodeElement:
    return NodeElement(
        data=NodeData(id=node_id, label=label, type=node_type, layer=layer, **kwargs),
        position={"x": 0, "y": 0},
    )


def _edge(edge_id: str, source: str, target: str, flow_type: str = "OTF", **kwargs) -> EdgeElement:
    return EdgeElement(data=EdgeData(id=edge_id, source=source, target=target, flow_type=flow_type, **kwargs))


def _row_values(panel) -> dict[str, str]:
    values: dict[str, str] = {}
    for section in panel.sections:
        for row in section.rows:
            values[row.label] = row.value
    return values


def _section(panel, title: str):
    return next(section for section in panel.sections if section.title == title)


def test_graph_overview_hides_video_timing_for_audio_only_scenario_and_explains_level2_unavailable():
    view = ViewResponse(
        level=2,
        mode="drilldown",
        scenario_id="uc-audio-mp3-playback",
        variant_id="audio-aac-bt-screen-on",
        summary=_summary(name="Audio Streaming", resolution="unknown"),
        nodes=[],
        edges=[],
        risks=[],
        metadata={
            "expand": "csispdp",
            "level2_available": False,
            "unavailable_reasons": ["No active pipeline nodes match expand='csispdp'."],
            "required_data": ["capabilities.properties.modules for module nodes"],
        },
    )

    panel = build_graph_overview(view)
    rows = _row_values(panel)
    unavailable = _section(panel, "Unavailable")

    assert panel.title == "Graph Overview"
    assert "Frame Rate" not in rows
    assert "Period" not in rows
    assert rows["Scenario"] == "Audio Streaming"
    assert rows["Level"] == "2"
    assert rows["Expand"] == "csispdp"
    assert "No active pipeline nodes" in unavailable.notes[0]
    assert "capabilities.properties.modules" in unavailable.notes[1]


def test_node_inspector_shows_ip_hierarchy_operations_buffers_memory_llc_sim_and_risks():
    view = ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "ip-yuvsc",
                "YUVSC",
                "ip",
                "hw",
                ip_ref="YUVSC",
                hierarchy_group="ISP",
                ip_group="YUV scaler",
                dvfs_group="isp",
                role_hw_name="Scaler",
                summary_badges=["camera"],
                capability_badges=["CROP", "SCALE", "HDR10"],
                active_operations=OperationSummary(crop=True, scale=True, scale_from="4000x2250", scale_to="1920x1080"),
                memory=MemoryDescriptor(
                    format="YUV422",
                    bitdepth=10,
                    width=1920,
                    height=1080,
                    fps=30,
                    compression="COMP_OFF",
                    size_bytes=8294400,
                ),
                placement=MemoryPlacement(llc_allocated=True, llc_policy="dedicated", llc_allocation_mb=1.0),
                matched_issues=["risk-bw"],
                detail_items=["Input: CSISPDP_3AA_BUF", "Output: YUVSC_MTNR_BUF"],
                sim_overlay=SimOverlay(power_mw=42.0, set_clock_mhz=533.0, hw_time_ms=2.4),
            ),
            _node("buf-in", "Csispdp 3Aa Buf", "buffer", "memory"),
            _node("buf-out", "Yuvsc Mtnr Buf", "buffer", "memory"),
        ],
        edges=[
            _edge("e-in", "buf-in", "ip-yuvsc", "M2M", buffer_ref="CSISPDP_3AA_BUF", producer="CSISPDP", consumer="YUVSC"),
            _edge("e-out", "ip-yuvsc", "buf-out", "M2M", buffer_ref="YUVSC_MTNR_BUF", producer="YUVSC", consumer="MTNR"),
        ],
        risks=[
            RiskCard(
                id="risk-bw",
                title="DRAM Bandwidth High",
                component="YUVSC",
                description="Bandwidth is high.",
                severity="Medium",
                impact="Throughput Risk",
            )
        ],
    )

    panel = build_node_inspector(view, "ip-yuvsc")
    rows = _row_values(panel)
    io_section = _section(panel, "Buffer I/O")
    risk_section = _section(panel, "Risks")

    assert panel.title == "YUVSC"
    assert rows["Type"] == "ip"
    assert rows["Hierarchy"] == "ISP"
    assert rows["IP Block"] == "YUV scaler"
    assert rows["Role HW"] == "Scaler"
    assert rows["Operations"] == "Crop, Scale 4000x2250 -> 1920x1080"
    assert rows["Memory"] == "YUV422 / 1920x1080 / 30fps / 10b / COMP_OFF / 8294400 B"
    assert rows["LLC"] == "dedicated 1MB"
    assert rows["Simulation"] == "42mW / 533MHz / 2.4ms"
    assert any("Input: CSISPDP_3AA_BUF" in note for note in io_section.notes)
    assert any("Output: YUVSC_MTNR_BUF" in note for note in io_section.notes)
    assert risk_section.notes == ["Medium: DRAM Bandwidth High - Throughput Risk"]


def test_module_node_inspector_prioritizes_level2_module_fields():
    view = ViewResponse(
        level=2,
        mode="drilldown:csispdp",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "mod-csispdp-wdma",
                "CSISPDP WDMA",
                "submodule",
                "hw",
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                module_ref="CSISPDP_WDMA",
                module_kind="wdma",
                module_direction="output",
                module_status="active",
                port_ref="WDMA0",
            )
        ],
        edges=[],
    )

    rows = _row_values(build_node_inspector(view, "mod-csispdp-wdma"))

    assert rows["Module"] == "CSISPDP_WDMA"
    assert rows["Module Kind"] == "wdma"
    assert rows["Direction"] == "output"
    assert rows["Status"] == "active"
    assert rows["Port"] == "WDMA0"


def test_edge_inspector_shows_route_buffer_memory_llc_and_simulation():
    view = ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node("ip-csispdp", "CSISPDP", "ip", "hw"),
            _node("ip-3aa", "N3AA", "ip", "hw"),
        ],
        edges=[
            _edge(
                "e-csis-3aa",
                "ip-csispdp",
                "ip-3aa",
                "M2M",
                latency_class="frame_buffered",
                buffer_ref="CSISPDP_3AA_BUF",
                producer="CSISPDP",
                consumer="N3AA",
                memory=MemoryDescriptor(format="RAW_BAYER_16", bitdepth=12, width=4000, height=2250, fps=30),
                placement=MemoryPlacement(llc_allocated=True, llc_policy="shared", llc_allocation_mb=2.0),
                sim_overlay=EdgeSimOverlay(bw_mbs=900.0, bw_power_mw=12.5),
                detail_items=["DMA write then read"],
            )
        ],
    )

    panel = build_edge_inspector(view, "e-csis-3aa")
    rows = _row_values(panel)
    details = _section(panel, "Details")

    assert panel.title == "CSISPDP -> N3AA"
    assert rows["Flow"] == "M2M"
    assert rows["Latency"] == "frame_buffered"
    assert rows["Buffer"] == "CSISPDP_3AA_BUF"
    assert rows["Producer"] == "CSISPDP"
    assert rows["Consumer"] == "N3AA"
    assert rows["Memory"] == "RAW_BAYER_16 / 4000x2250 / 30fps / 12b"
    assert rows["LLC"] == "shared 2MB"
    assert rows["Simulation"] == "900MB/s / 12.5mW"
    assert details.notes == ["DMA write then read"]


def test_inspector_options_exclude_layout_nodes_and_format_edges_with_node_labels():
    view = ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node("grp-isp", "ISP", "submodule", "meta"),
            _node("ip-cstat", "CSTAT", "ip", "hw"),
            _node("stage-0", "Stage", "stage_header", "meta"),
            _node("lane-hw", "HW", "lane_label", "meta"),
        ],
        edges=[_edge("e-cstat-isp", "ip-cstat", "grp-isp", "OTF", buffer_ref="CSTAT_OUT")],
    )

    assert [option.id for option in node_options(view)] == ["grp-isp", "ip-cstat"]
    edge = edge_options(view)[0]
    assert edge.id == "e-cstat-isp"
    assert edge.label == "CSTAT -> ISP (CSTAT_OUT)"


def test_level0_inspector_uses_topology_view_as_node_edge_source():
    resource_view = ViewResponse(
        level=0,
        mode="resource",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[],
        edges=[],
    )
    topology_view = ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[_node("ip-cstat", "CSTAT", "ip", "hw")],
        edges=[],
    )

    assert inspector_view_source(0, resource_view, topology_view) is topology_view
    assert inspector_view_source(1, resource_view, topology_view) is resource_view


def test_inspector_heading_is_not_rendered_as_empty_detail_panel():
    html = inspector_heading_html("Graph Inspector")

    assert "Graph Inspector" in html
    assert "detail-panel" not in html
