from __future__ import annotations

from dashboard.components.elk_viewer import build_elk_graph, build_elk_view_html
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


def test_elk_html_escapes_script_breakout_inside_json_payload():
    view = ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-script-safety",
        variant_id="safe-json",
        summary=_summary(),
        nodes=[
            _node(
                "node-script",
                "</script><script>alert(1)</script>",
                "sw",
                "app",
                100,
                80,
            ),
        ],
        edges=[],
        metadata={"layout": "layered-lanes"},
    )

    html = build_elk_view_html(view)

    assert "</script><script>alert(1)</script>" not in html
    assert "<\\/script><script>alert(1)<\\/script>" in html


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


def test_detail_view_uses_explicit_parent_for_nested_groups_even_when_coordinates_do_not_contain_nodes():
    view = ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "grp-isp",
                "ISP",
                "submodule",
                "meta",
                100,
                100,
                hierarchy_group="ISP",
                view_hints=ViewHints(width=180, height=120),
            ),
            _node(
                "grp-isp-byrp",
                "BYRP",
                "submodule",
                "meta",
                900,
                900,
                parent="grp-isp",
                hierarchy_group="ISP",
                ip_group="BYRP",
                view_hints=ViewHints(width=160, height=100),
            ),
            _node(
                "ip-byrp",
                "BYRP",
                "ip",
                "hw",
                1400,
                1400,
                parent="grp-isp-byrp",
                hierarchy_group="ISP",
                ip_group="BYRP",
            ),
            _node("ip-mfc", "MFC", "ip", "hw", 1400, 100, hierarchy_group="CODEC", ip_group="MFC"),
        ],
        edges=[_edge("e-byrp-mfc", "ip-byrp", "ip-mfc", "M2M")],
        metadata={"layout": "level1-semantic-ip-dag"},
    )

    graph, meta = build_elk_graph(view)

    isp_group = next(child for child in graph["children"] if child["id"] == "grp-isp")
    byrp_group = next(child for child in isp_group["children"] if child["id"] == "grp-isp-byrp")
    assert {child["id"] for child in byrp_group["children"]} == {"ip-byrp"}
    assert any(child["id"] == "ip-mfc" for child in graph["children"])
    assert meta["grp-isp"]["semantic_group"] == "ISP"
    assert meta["grp-isp-byrp"]["ip_group"] == "BYRP"
    assert meta["grp-isp"]["fill"] != meta["grp-isp-byrp"]["fill"]


def test_detail_view_styles_compute_hierarchy_and_gpu_ip_group_without_fallback_colors():
    view = ViewResponse(
        level=1,
        mode="level1-ip-detail",
        scenario_id="uc-game-play",
        variant_id="game-fhd-60fps-npu-ai",
        summary=_summary(),
        nodes=[
            _node(
                "grp-compute",
                "Compute",
                "submodule",
                "meta",
                100,
                100,
                hierarchy_group="Compute",
                view_hints=ViewHints(width=220, height=160),
            ),
            _node(
                "grp-compute-sgpu",
                "SGPU",
                "submodule",
                "meta",
                300,
                300,
                parent="grp-compute",
                hierarchy_group="Compute",
                ip_group="SGPU",
                view_hints=ViewHints(width=180, height=120),
            ),
            _node(
                "ip-gpu",
                "GPU",
                "ip",
                "hw",
                500,
                500,
                parent="grp-compute-sgpu",
                hierarchy_group="Compute",
                ip_group="SGPU",
            ),
        ],
        edges=[],
        metadata={"layout": "level1-semantic-ip-dag"},
    )

    _, meta = build_elk_graph(view)

    assert meta["grp-compute"]["fill"] != "#F8FAFC"
    assert meta["grp-compute-sgpu"]["fill"] != "#F8FAFC"
    assert meta["grp-compute"]["fill"] != meta["grp-compute-sgpu"]["fill"]


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


def test_level2_module_meta_uses_module_kind_direction_and_distinct_styles():
    view = ViewResponse(
        level=2,
        mode="drilldown:csispdp",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "l2pkg-csispdp",
                "CSISPDP",
                "submodule",
                "meta",
                100,
                100,
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                view_hints=ViewHints(width=220, height=160),
            ),
            _node(
                "mod-csispdp-csispdp",
                "CSISPDP",
                "submodule",
                "hw",
                140,
                160,
                parent="l2pkg-csispdp",
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                module_ref="CSISPDP",
                module_kind="functional",
            ),
            _node(
                "mod-csispdp-csispdp-wdma",
                "CSISPDP WDMA",
                "submodule",
                "hw",
                340,
                160,
                parent="l2pkg-csispdp",
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                module_ref="CSISPDP_WDMA",
                module_kind="wdma",
                module_direction="output",
            ),
        ],
        edges=[],
        metadata={"layout": "level2-module-detail"},
    )

    _, meta = build_elk_graph(view)

    assert meta["mod-csispdp-csispdp"]["fill"] == meta["l2pkg-csispdp"]["fill"]
    assert meta["mod-csispdp-csispdp-wdma"]["fill"] != meta["mod-csispdp-csispdp"]["fill"]
    assert meta["mod-csispdp-csispdp-wdma"]["subtitle"] == "output / WDMA"
    assert "Module kind: wdma" in meta["mod-csispdp-csispdp-wdma"]["details"]


def test_level2_html_uses_local_elk_runtime_and_readable_initial_view():
    view = ViewResponse(
        level=2,
        mode="drilldown:camera",
        scenario_id="uc-camera-recording",
        variant_id="cam-rec-3rdparty-binning",
        summary=_summary(),
        nodes=[
            _node(
                "l2pkg-csispdp",
                "CSISPDP",
                "submodule",
                "meta",
                100,
                100,
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                view_hints=ViewHints(width=220, height=160),
            ),
            _node(
                "mod-csispdp-csispdp",
                "CSISPDP",
                "submodule",
                "hw",
                140,
                160,
                parent="l2pkg-csispdp",
                hierarchy_group="ISP",
                ip_group="CSIS/PDP",
                module_ref="CSISPDP",
                module_kind="functional",
            ),
        ],
        edges=[],
        metadata={"layout": "level2-module-detail"},
    )

    html = build_elk_view_html(view, canvas_height=980, title="Level 2 - Drill Down (camera)")

    assert "cdn.jsdelivr.net/npm/elkjs" not in html
    assert "function initialGraphView()" in html
    assert "level2-module-detail" in html
    assert "readableLevel2View();" in html


def test_m2m_edge_label_carries_full_transfer_descriptor():
    from scenario_db.api.schemas.view import EdgeData, EdgeSimOverlay, MemoryDescriptor

    from dashboard.components.elk_viewer import _edge_meta

    edge = EdgeElement(
        data=EdgeData(
            id="e-csis-mfc",
            source="csis",
            target="mfc",
            flow_type="M2M",
            buffer_ref="CSIS_WDMA_BUF",
            memory=MemoryDescriptor(format="BAYER_PACKED", bitdepth=12, width=4000, height=2252, compression="COMP"),
            sim_overlay=EdgeSimOverlay(bw_mbs=420.5),
        )
    )

    meta = _edge_meta(edge)

    assert meta["label"] == "CSIS_WDMA_BUF | 4000x2252 | BAYER_PACKED | 12b | COMP | 420.5MB/s"


def test_edge_without_memory_keeps_flow_type_label():
    from dashboard.components.elk_viewer import _edge_meta

    meta = _edge_meta(_edge("e-plain", "a", "b", "OTF"))

    assert meta["label"] == "OTF"


def test_display_label_prefers_descriptor_over_backend_label():
    from scenario_db.api.schemas.view import EdgeData, MemoryDescriptor

    from dashboard.components.elk_viewer import _edge_display_label, _edge_meta

    edge = EdgeElement(
        data=EdgeData(
            id="e-mcsc-gdc",
            source="mcsc",
            target="gdc_m",
            flow_type="M2M",
            label="MEM / MCSC_WDMA_PREV_BUF",
            buffer_ref="MCSC_WDMA_PREV_BUF",
            memory=MemoryDescriptor(format="YUV420", bitdepth=8, width=4000, height=2250),
        )
    )

    label = _edge_display_label(edge.data, _edge_meta(edge))

    assert label == "MCSC_WDMA_PREV_BUF | 4000x2250 | YUV420 | 8b"


def test_display_label_falls_back_to_backend_label_without_memory():
    from scenario_db.api.schemas.view import EdgeData

    from dashboard.components.elk_viewer import _edge_display_label, _edge_meta

    edge = EdgeElement(
        data=EdgeData(
            id="e-plain2",
            source="a",
            target="b",
            flow_type="M2M",
            label="MEM / SOME_BUF",
        )
    )

    assert _edge_display_label(edge.data, _edge_meta(edge)) == "MEM / SOME_BUF"


def test_scale_operation_subtitle_shows_size_transition():
    from scenario_db.api.schemas.view import OperationSummary

    from dashboard.components.elk_viewer import _node_meta

    node = _node(
        "ip-mlsc",
        "MLSC",
        "ip",
        "hw",
        0,
        0,
        active_operations=OperationSummary(scale=True, scale_from="4000x2252", scale_to="1920x1080"),
    )

    assert _node_meta(node)["subtitle"] == "4000x2252→1920x1080"


def test_static_runtime_variant_references_static_route_instead_of_inlining():
    from dashboard.components.elk_viewer import STATIC_ELK_URL, _html

    inline_html = _html({}, {}, "T", 100, inline_runtime=True)
    static_html = _html({}, {}, "T", 100, inline_runtime=False)

    assert f'<script src="{STATIC_ELK_URL}"></script>' in static_html
    # The static variant must not carry the 1.6MB inlined library.
    assert len(static_html) < 120_000
    assert len(inline_html) > len(static_html)
