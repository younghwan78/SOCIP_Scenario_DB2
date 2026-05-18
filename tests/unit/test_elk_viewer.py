from __future__ import annotations

from dashboard.components.elk_viewer import build_elk_graph
from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    MemoryDescriptor,
    MemoryPlacement,
    NodeData,
    NodeElement,
    OperationSummary,
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


def _all_child_ids(graph: dict) -> set[str]:
    ids: set[str] = set()
    for child in graph.get("children", []):
        ids.add(child["id"])
        ids.update(_all_child_ids(child))
    return ids


def _rects_overlap(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


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
            _node(
                "buf-record",
                "Record Buffer",
                "buffer",
                "memory",
                100,
                580,
                memory=MemoryDescriptor(format="NV12", width=3840, height=2160, fps=60, compression="SBWC"),
            ),
        ],
        edges=[
            _edge("e-app-fw", "app-camera", "fw-camera", "control"),
            _edge("e-isp-buf", "ip-isp0", "buf-record", "M2M"),
        ],
        metadata={"layout": "layered-lanes"},
    )

    graph, meta = build_elk_graph(view)

    group_ids = _all_child_ids(graph)
    assert graph["manualLayout"] is True
    assert {"layer-app", "layer-framework", "layer-hal", "layer-kernel", "layer-hw", "layer-memory"} <= group_ids
    layer_pos = {child["id"]: child for child in graph["children"]}
    assert layer_pos["layer-app"]["y"] == layer_pos["layer-framework"]["y"]
    assert layer_pos["layer-hal"]["y"] == layer_pos["layer-kernel"]["y"]
    assert layer_pos["layer-hw"]["y"] == layer_pos["layer-memory"]["y"]
    assert layer_pos["layer-app"]["x"] < layer_pos["layer-framework"]["x"]
    assert layer_pos["layer-hal"]["x"] < layer_pos["layer-kernel"]["x"]
    assert layer_pos["layer-hw"]["x"] < layer_pos["layer-memory"]["x"]
    assert all(edge.get("sections") for edge in graph["edges"])
    visible_edges = [edge for edge in graph["edges"] if not meta[edge["id"]].get("hidden")]
    assert len(visible_edges) == 2
    app_fw = next(edge for edge in visible_edges if edge["id"] == "e-app-fw")
    app_node = next(child for child in layer_pos["layer-app"]["children"] if child["id"] == "app-camera")
    fw_node = next(child for child in layer_pos["layer-framework"]["children"] if child["id"] == "fw-camera")
    section = app_fw["sections"][0]
    assert section["startPoint"]["x"] == layer_pos["layer-app"]["x"] + app_node["x"] + app_node["width"]
    assert section["startPoint"]["y"] == layer_pos["layer-app"]["y"] + app_node["y"] + app_node["height"] / 2
    assert section["endPoint"]["x"] == layer_pos["layer-framework"]["x"] + fw_node["x"]
    assert section["endPoint"]["y"] == layer_pos["layer-framework"]["y"] + fw_node["y"] + fw_node["height"] / 2
    assert meta["layer-app"]["label"] == "App"
    assert meta["buf-record"]["type"] == "buffer"
    assert meta["buf-record"]["subtitle"] == "NV12 / 3840x2160 / 60fps / SBWC"


def test_level0_layer_groups_do_not_overlap_with_varied_node_counts():
    nodes = []
    for idx in range(3):
        nodes.append(_node(f"app-{idx}", f"App {idx}", "sw", "app", 100, 80 + idx * 30))
    for idx in range(4):
        nodes.append(_node(f"fw-{idx}", f"Framework {idx}", "sw", "framework", 260, 80 + idx * 30))
    for idx in range(3):
        nodes.append(_node(f"hal-{idx}", f"HAL {idx}", "sw", "hal", 100, 260 + idx * 30))
    for idx in range(4):
        nodes.append(_node(f"kern-{idx}", f"Kernel {idx}", "sw", "kernel", 260, 260 + idx * 30))
    for idx in range(3):
        nodes.append(_node(f"ip-{idx}", f"IP {idx}", "ip", "hw", 100, 460 + idx * 30))
    for idx in range(3):
        nodes.append(_node(f"buf-{idx}", f"Buffer {idx}", "buffer", "memory", 260, 460 + idx * 30))

    view = ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-audio-playback",
        variant_id="screen-on",
        summary=_summary(),
        nodes=nodes,
        edges=[],
        metadata={"layout": "layered-lanes"},
    )

    graph, _ = build_elk_graph(view)
    groups = graph["children"]
    for idx, group in enumerate(groups):
        for other in groups[idx + 1 :]:
            assert not _rects_overlap(group, other), f"{group['id']} overlaps {other['id']}"


def test_level0_facing_vertical_otf_edge_does_not_stub_past_target():
    view = ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-preview",
        variant_id="cam-prev-f1-30",
        summary=_summary(),
        nodes=[
            _node("res-camera_frontend", "Camera Frontend", "ip", "hw", 100, 480),
            _node("res-isp", "ISP", "ip", "hw", 100, 580),
        ],
        edges=[
            _edge("e-camera-isp", "res-camera_frontend", "res-isp", "OTF"),
        ],
        metadata={"layout": "layered-lanes"},
    )

    graph, _ = build_elk_graph(view)
    edge = graph["edges"][0]
    section = edge["sections"][0]
    start_y = section["startPoint"]["y"]
    end_y = section["endPoint"]["y"]
    for point in section["bendPoints"]:
        assert start_y <= point["y"] <= end_y


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


def test_level0_topology_meta_distinguishes_subsystems_sw_ops_and_llc_buffers():
    view = ViewResponse(
        level=0,
        mode="topology",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-r1-fhd30",
        summary=_summary(),
        nodes=[
            _node(
                "ip-isp",
                "ISP",
                "ip",
                "hw",
                100,
                100,
                summary_badges=["camera"],
                active_operations=OperationSummary(scale=True, crop=True),
            ),
            _node("ip-gpu", "GPU", "ip", "hw", 300, 100, summary_badges=["display"]),
            _node("sw-filter", "SW Filter", "sw", "kernel", 500, 100),
            _node(
                "buf-record",
                "Record Buffer",
                "buffer",
                "memory",
                700,
                100,
                memory=MemoryDescriptor(format="NV12", width=1920, height=1080, compression="SBWC_v4"),
                placement=MemoryPlacement(llc_allocated=True, llc_policy="dedicated", llc_allocation_mb=1.0),
            ),
        ],
        edges=[],
        metadata={"layout": "level0-resource-topology"},
    )

    _, meta = build_elk_graph(view)

    assert meta["ip-isp"]["fill"] != meta["ip-gpu"]["fill"]
    assert meta["ip-isp"]["fill"] != meta["buf-record"]["fill"]
    assert meta["sw-filter"]["subtitle"] == "<sw>"
    assert meta["ip-isp"]["subtitle"] == "Crop / Scale"
    assert "LLC dedicated 1MB" in meta["buf-record"]["subtitle"]
