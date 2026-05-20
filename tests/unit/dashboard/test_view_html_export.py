from __future__ import annotations

from dashboard.components.view_html_export import (
    DEFAULT_EXPORT_SCOPE,
    ExportDiagram,
    ViewExportBundle,
    ViewExportOptions,
    build_static_view_html,
    export_filename,
)
from scenario_db.api.schemas.view import (
    BufferHandoffSummary,
    DisplayCompositionSummary,
    DisplayLayerSummary,
    EdgeData,
    EdgeElement,
    IoSummary,
    Level0MetricBreakdown,
    Level0ResourceOverview,
    MemoryDescriptor,
    NodeData,
    NodeElement,
    ResourceOverviewRow,
    SensorEndpointSummary,
    ViewResponse,
    ViewSummary,
)


def _summary() -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        name="Camera Recording",
        subtitle="FHD 30fps",
        period_ms=33.33,
        budget_ms=30.0,
        resolution="1920 x 1080",
        fps=30,
        variant_label="soc-exynos2600",
    )


def _node(node_id: str, label: str, node_type: str = "ip", layer: str = "hw", **kwargs) -> NodeElement:
    return NodeElement(
        data=NodeData(id=node_id, label=label, type=node_type, layer=layer, **kwargs),
        position={"x": 100, "y": 100},
    )


def _edge(edge_id: str, source: str, target: str, **kwargs) -> EdgeElement:
    return EdgeElement(data=EdgeData(id=edge_id, source=source, target=target, flow_type="M2M", **kwargs))


def _resource_view() -> ViewResponse:
    overview = Level0ResourceOverview(
        rows=[
            ResourceOverviewRow(
                sequence_index=1,
                node_id="sensor_rear",
                label="Rear Sensor",
                resource_domain="external_source",
                resource_kind="sensor",
                subsystem="camera",
                output=IoSummary(width=4000, height=2250, fps=30, format="RAW10", bitdepth=10),
                flow="OTF",
                buffer_refs=["CSISPDP_3AA_BUF"],
                badges=["RAW"],
            ),
            ResourceOverviewRow(
                sequence_index=2,
                node_id="csispdp",
                label="CSISPDP",
                resource_domain="soc_resource",
                resource_kind="camera",
                subsystem="camera",
                input=IoSummary(width=4000, height=2250, fps=30, format="RAW10", bitdepth=10),
                output=IoSummary(width=4000, height=2250, fps=30, format="RAW_BAYER_16", bitdepth=12),
                flow="M2M",
                buffer_refs=["CSISPDP_3AA_BUF"],
                badges=["LLC"],
            ),
        ],
        buffers=[
            BufferHandoffSummary(
                buffer_ref="CSISPDP_3AA_BUF",
                subsystem="camera",
                producer_node_id="csispdp",
                consumer_node_ids=["n3aa"],
                size_label="4000x2250",
                format="RAW_BAYER_16",
                bitdepth=12,
                compression="COMP_BAYER_LOSSLESS",
                comp_ratio=1.6,
                llc_allocated=True,
                llc_policy="dedicated",
                llc_allocation_mb=2.0,
            )
        ],
        metric_breakdown=[
            Level0MetricBreakdown(subsystem="camera", node_count=2, power_mw=10.0, bw_total_mbs=900.0, warning_count=0)
        ],
        sensors=[
            SensorEndpointSummary(
                node_id="sensor_rear",
                sensor_mode="binning_4x4",
                module_ref="rear_wide",
                output=IoSummary(width=4000, height=2250, fps=30, format="RAW10", bitdepth=10),
                downstream=["csispdp"],
            )
        ],
        displays=[
            DisplayCompositionSummary(
                node_id="display",
                composer="DPU_DIRECT",
                layer_count=1,
                panel_mode="120hz",
                output=IoSummary(width=1080, height=2340, fps=120, format="RGB"),
                layers=[
                    DisplayLayerSummary(
                        name="Camera Preview",
                        buffer_ref="preview_buf",
                        format="YUV420",
                        src_frame="0,0 1920x1080",
                        dst_frame="0,96 1080x1920",
                    )
                ],
            )
        ],
    )
    return ViewResponse(
        level=0,
        mode="resource",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[],
        edges=[],
        metadata={"layout": "level0-resource-overview"},
        level0_resource_overview=overview,
    )


def _graph_view(level: int, mode: str, title_node: str = "CSISPDP") -> ViewResponse:
    return ViewResponse(
        level=level,
        mode=mode,
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "ip-csispdp",
                title_node,
                ip_ref="CSISPDP",
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                memory=MemoryDescriptor(format="RAW_BAYER_16", width=4000, height=2250, fps=30, bitdepth=12),
                detail_items=["Output: CSISPDP_3AA_BUF"],
            ),
            _node("ip-n3aa", "N3AA", ip_ref="N3AA", hierarchy_group="ISP", ip_group="3AA/CSTAT"),
        ],
        edges=[
            _edge(
                "e-csispdp-n3aa",
                "ip-csispdp",
                "ip-n3aa",
                buffer_ref="CSISPDP_3AA_BUF",
                producer="CSISPDP",
                consumer="N3AA",
                memory=MemoryDescriptor(format="RAW_BAYER_16", width=4000, height=2250, fps=30, bitdepth=12),
            )
        ],
        metadata={"layout": "level1-semantic-ip-dag" if level == 1 else "level2-module-detail"},
    )


def test_build_static_view_html_unifies_resource_tables_diagrams_inspector_and_raw_json():
    level0_topology = _graph_view(0, "topology")
    level1 = _graph_view(1, "level1-ip-detail")
    level2 = _graph_view(2, "drilldown:csispdp")
    unavailable = ViewResponse(
        level=2,
        mode="drilldown:gpu",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[],
        edges=[],
        metadata={
            "expand": "gpu",
            "layout": "level2-unavailable",
            "level2_available": False,
            "unavailable_reasons": ["No module-level declaration for GPU."],
            "required_data": ["capabilities.properties.modules"],
        },
    )
    bundle = ViewExportBundle(
        title="Camera Recording Export",
        resource_view=_resource_view(),
        diagrams=[
            ExportDiagram("Level 0 - Topology Overview", level0_topology, 960),
            ExportDiagram("Level 1 - IP Detail DAG", level1, 980),
            ExportDiagram("Level 2 - Drill Down (csispdp)", level2, 900),
            ExportDiagram("Level 2 - Drill Down (gpu)", unavailable, 640),
        ],
        inspector_views=[level0_topology, level1, level2, unavailable],
    )

    html = build_static_view_html(bundle, ViewExportOptions(scope="full_drilldown", include_raw_json=True))

    assert "<!doctype html>" in html
    assert "Camera Recording Export" in html
    assert "Scenario Resource Overview" in html
    assert "Buffer Handoffs" in html
    assert "Sensor Endpoints" in html
    assert "Display Composition" in html
    assert "Subsystem Summary" in html
    assert "Level 0 - Topology Overview" in html
    assert "Level 1 - IP Detail DAG" in html
    assert "Level 2 - Drill Down (csispdp)" in html
    assert "Level 2 - Drill Down (gpu)" in html
    assert "No module-level declaration for GPU." in html
    assert "Graph Inspector" in html
    assert "Node Catalog" in html
    assert "Edge Catalog" in html
    assert "CSISPDP -&gt; N3AA" in html
    assert "Raw ViewResponse JSON" in html
    assert "CSISPDP_3AA_BUF" in html
    assert "<iframe" in html
    assert "srcdoc=" in html


def test_build_static_view_html_can_exclude_raw_json():
    bundle = ViewExportBundle(
        title="Camera Recording Export",
        resource_view=_resource_view(),
        diagrams=[ExportDiagram("Level 1 - IP Detail DAG", _graph_view(1, "level1-ip-detail"), 900)],
        inspector_views=[],
    )

    html = build_static_view_html(bundle, ViewExportOptions(scope="scenario_pack", include_raw_json=False))

    assert "Raw ViewResponse JSON" not in html
    assert "Level 1 - IP Detail DAG" in html


def test_export_filename_is_stable_and_safe():
    assert (
        export_filename("Camera Recording", "cam-rec/3rdparty:binning", "full_drilldown")
        == "scenario-view-camera-recording-cam-rec-3rdparty-binning-full-drilldown.html"
    )


def test_full_drilldown_is_default_export_scope_and_raw_json_is_opt_in():
    assert DEFAULT_EXPORT_SCOPE == "full_drilldown"
    assert ViewExportOptions().include_raw_json is False
