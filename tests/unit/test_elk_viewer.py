from __future__ import annotations

from dashboard.components.elk_viewer import build_elk_graph
from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    NodeData,
    NodeElement,
    ViewHints,
    ViewResponse,
    ViewSummary,
)


def _summary() -> ViewSummary:
    return ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="UHD60-HDR10-H265",
        name="Camera Recording Pipeline",
        subtitle="UHD 60fps",
        period_ms=16.67,
        budget_ms=15.0,
        resolution="3840 x 2160",
        fps=60,
        variant_label="soc-exynos2500",
    )


def _node(node_id: str, label: str, node_type: str, layer: str, x: float, y: float, **kwargs) -> NodeElement:
    return NodeElement(
        data=NodeData(id=node_id, label=label, type=node_type, layer=layer, **kwargs),
        position={"x": x, "y": y},
    )


def _edge(edge_id: str, source: str, target: str, flow_type: str = "OTF") -> EdgeElement:
    return EdgeElement(data=EdgeData(id=edge_id, source=source, target=target, flow_type=flow_type))


def test_level0_architecture_is_converted_to_layer_hierarchy():
    view = ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-recording",
        variant_id="UHD60-HDR10-H265",
        summary=_summary(),
        nodes=[
            _node("app-camera", "Camera App", "sw", "app", 100, 80),
            _node("fw-camera", "CameraService", "sw", "framework", 100, 180),
            _node("hal-camera", "Camera HAL", "sw", "hal", 100, 280),
            _node("drv-camera", "V4L2 Driver", "sw", "kernel", 100, 380),
            _node("ip-isp0", "ISP0", "ip", "hw", 100, 480),
            _node("buf-record", "Record Buffer", "buffer", "memory", 100, 580),
        ],
        edges=[
            _edge("e-app-fw", "app-camera", "fw-camera", "control"),
            _edge("e-isp-buf", "ip-isp0", "buf-record", "M2M"),
        ],
        metadata={"layout": "layered-lanes"},
    )

    graph, meta = build_elk_graph(view)

    group_ids = {child["id"] for child in graph["children"]}
    assert {"layer-app", "layer-framework", "layer-hal", "layer-kernel", "layer-hw", "layer-memory"} <= group_ids
    visible_edges = [edge for edge in graph["edges"] if not meta[edge["id"]].get("hidden")]
    assert len(visible_edges) == 2
    assert any(meta[edge["id"]].get("hidden") for edge in graph["edges"])
    assert meta["layer-app"]["label"] == "App"
    assert meta["buf-record"]["type"] == "buffer"


def test_detail_view_keeps_group_boxes_as_compound_nodes():
    view = ViewResponse(
        level=1,
        mode="ip-detail",
        scenario_id="uc-camera-recording",
        variant_id="UHD60-HDR10-H265",
        summary=_summary(),
        nodes=[
            _node(
                "grp-isp",
                "ISP",
                "submodule",
                "meta",
                300,
                300,
                view_hints=ViewHints(width=500, height=400),
            ),
            _node("t_csis", "CSIS", "submodule", "hw", 220, 180),
            _node("t_cstat", "CSTAT", "submodule", "hw", 320, 300),
            _node("t_mfc", "MFC", "ip", "hw", 900, 680),
        ],
        edges=[
            _edge("e-csis-cstat", "t_csis", "t_cstat", "OTF"),
            _edge("e-cstat-mfc", "t_cstat", "t_mfc", "M2M"),
        ],
        metadata={"layout": "level1-reference"},
    )

    graph, meta = build_elk_graph(view)

    isp_group = next(child for child in graph["children"] if child["id"] == "grp-isp")
    child_ids = {child["id"] for child in isp_group["children"]}
    assert {"t_csis", "t_cstat"} <= child_ids
    assert any(child["id"] == "t_mfc" for child in graph["children"])
    assert meta["e-cstat-mfc"]["flow_type"] == "M2M"
