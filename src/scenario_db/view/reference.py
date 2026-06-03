"""Legacy/reference view projections kept outside the projection service."""
from __future__ import annotations

from typing import Any

from scenario_db.api.schemas.view import EdgeElement, MemoryDescriptor, MemoryPlacement, NodeElement, OperationSummary, ViewHints, ViewResponse
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.buffers import (
    _buffer_detail_items,
    _buffer_memory_from_spec,
    _buffer_placement_from_spec,
    _reference_sizes,
)
from scenario_db.view.elements import _e, _n
from scenario_db.view.pipeline import _edge_detail_items, _task_edge_removed, _task_node_detail_items
from scenario_db.view.response import build_view_response as _response

def _ref_task_node(
    node_id: str,
    label: str,
    x: float,
    y: float,
    *,
    layer: str = "hw",
    width: int = 132,
    height: int = 52,
    ip_ref: str | None = None,
    badges: list[str] | None = None,
    ops: OperationSummary | None = None,
    memory: MemoryDescriptor | None = None,
    placement: MemoryPlacement | None = None,
    detail_items: list[str] | None = None,
) -> NodeElement:
    return _n(
        node_id,
        label,
        "sw" if layer in {"app", "framework", "hal", "kernel"} else "ip",
        layer,
        x,
        y,
        ip_ref=ip_ref,
        summary_badges=["task"],
        capability_badges=badges or [],
        active_operations=ops,
        memory=memory,
        placement=placement,
        detail_items=detail_items or [],
        view_hints=ViewHints(lane=layer, stage="processing", width=width, height=height),
    )

def _format_view_text(template: Any, tokens: dict[str, str]) -> str:
    text = str(template or "")
    for key, value in tokens.items():
        text = text.replace("{" + key + "}", value)
    return text

def _token_value(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, str):
        return tokens.get(value, _format_view_text(value, tokens))
    return value

def _operation_from_spec(spec: dict[str, Any], tokens: dict[str, str]) -> OperationSummary | None:
    raw = spec.get("operations") or {}
    if not raw:
        return None
    return OperationSummary(
        crop=bool(raw.get("crop", False)),
        crop_ratio=raw.get("crop_ratio"),
        scale=bool(raw.get("scale", False)),
        scale_from=_token_value(raw.get("scale_from"), tokens),
        scale_to=_token_value(raw.get("scale_to"), tokens),
        rotate=raw.get("rotate"),
        compose=bool(raw.get("compose", False)),
        colorspace_convert=raw.get("colorspace_convert"),
    )

def _task_node_from_spec(
    graph: CanonicalScenarioGraph,
    spec: dict[str, Any],
    tokens: dict[str, str],
    override: dict[str, Any] | None = None,
) -> NodeElement:
    merged = dict(spec)
    if override:
        merged.update(override)
    layer = str(merged.get("layer") or "hw")
    return _ref_task_node(
        str(merged["id"]),
        _format_view_text(merged.get("label") or merged["id"], tokens),
        float(merged.get("x", 0)),
        float(merged.get("y", 0)),
        layer=layer,
        width=int(merged.get("width") or 132),
        height=int(merged.get("height") or 52),
        ip_ref=merged.get("ip_ref"),
        badges=list(merged.get("badges") or []),
        ops=_operation_from_spec(merged, tokens),
        memory=_buffer_memory_from_spec(graph, merged.get("buffer"), tokens),
        placement=_buffer_placement_from_spec(graph, merged.get("buffer")),
        detail_items=_task_node_detail_items(graph, str(merged["id"]), merged),
    )

def _flow_type_from_spec(value: Any) -> str:
    text = str(value or "M2M")
    if text in {"OTF", "vOTF", "M2M", "control", "risk"}:
        return text
    lowered = text.lower()
    if lowered == "otf":
        return "OTF"
    if lowered == "votf":
        return "vOTF"
    if lowered in {"sw", "control"}:
        return "control"
    return "M2M"

def _task_edges_from_spec(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
    tokens: dict[str, str],
    prefix: str,
) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    for idx, spec in enumerate(specs):
        buffer_ref = spec.get("buffer")
        edges.append(
            _e(
                str(spec.get("id") or f"{prefix}-{idx}"),
                str(spec.get("from")),
                str(spec.get("to")),
                _flow_type_from_spec(spec.get("type")),
                label=_format_view_text(spec.get("label") or spec.get("type") or "", tokens),
                buffer_ref=buffer_ref,
                memory=_buffer_memory_from_spec(graph, buffer_ref, tokens),
                placement=_buffer_placement_from_spec(graph, buffer_ref),
                detail_items=_edge_detail_items(graph, spec, buffer_ref),
            )
        )
    return edges

def _visible_task_node_specs(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[str]]:
    disabled = set(((getattr(graph.variant, "routing_switch", None) or {}).get("disabled_nodes") or []))
    visible = [spec for spec in specs if str(spec.get("id")) not in disabled]
    return visible, {str(spec.get("id")) for spec in visible}

def _visible_task_edge_specs(
    graph: CanonicalScenarioGraph,
    specs: list[dict[str, Any]],
    visible_node_ids: set[str],
) -> list[dict[str, Any]]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    patch = getattr(graph.variant, "topology_patch", None) or {}
    remove_specs = [
        *(routing.get("disabled_edges") or []),
        *(patch.get("remove_edges") or []),
    ]
    return [
        spec
        for spec in specs
        if str(spec.get("from")) in visible_node_ids
        and str(spec.get("to")) in visible_node_ids
        and not _task_edge_removed(spec, remove_specs)
    ]

def _project_task_graph_from_fixture(
    graph: CanonicalScenarioGraph,
    *,
    level: int,
    mode: str,
) -> ViewResponse | None:
    spec = (graph.scenario.pipeline or {}).get("task_graph") or {}
    task_nodes, visible_node_ids = _visible_task_node_specs(graph, spec.get("nodes") or [])
    if not task_nodes:
        return None
    tokens = _reference_sizes(graph)
    nodes = [_task_node_from_spec(graph, node_spec, tokens) for node_spec in task_nodes]
    edge_specs = _visible_task_edge_specs(graph, spec.get("edges") or [], visible_node_ids)
    edges = _task_edges_from_spec(graph, edge_specs, tokens, "task-edge")
    max_y = max((node.position["y"] for node in nodes), default=600)
    return _response(
        graph=graph,
        level=level,
        mode=mode,
        nodes=nodes,
        edges=edges,
        metadata={
            "canvas_w": 1100,
            "canvas_h": max(760, int(max_y + 160)),
            "layout": str(spec.get("layout") or "task-topology"),
        },
    )

def _project_level1_from_fixture(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    level1 = (graph.scenario.pipeline or {}).get("level1_graph") or {}
    task_graph = (graph.scenario.pipeline or {}).get("task_graph") or {}
    task_nodes, visible_node_ids = _visible_task_node_specs(graph, task_graph.get("nodes") or [])
    if not level1 or not task_nodes:
        return None
    tokens = _reference_sizes(graph)
    overrides = level1.get("node_overrides") or {}
    nodes = [
        _group_box(
            str(group["id"]),
            _format_view_text(group.get("label") or group["id"], tokens),
            float(group.get("x", 0)),
            float(group.get("y", 0)),
            int(group.get("width") or 200),
            int(group.get("height") or 120),
        )
        for group in level1.get("groups") or []
    ]
    for node_spec in task_nodes:
        node_id = str(node_spec.get("id"))
        override = overrides.get(node_id)
        if override is None and not level1.get("nodes_from_task_graph", False):
            continue
        nodes.append(_task_node_from_spec(graph, node_spec, tokens, override))

    edge_specs = _visible_task_edge_specs(graph, task_graph.get("edges") or [], visible_node_ids)
    edges = _task_edges_from_spec(graph, edge_specs, tokens, "level1-edge")
    return _response(
        graph=graph,
        level=1,
        mode="level1-ip-detail",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 1370, "layout": "level1-reference"},
    )

def _group_box(node_id: str, label: str, x: float, y: float, width: int, height: int) -> NodeElement:
    return _n(
        node_id,
        label,
        "submodule",
        "meta",
        x,
        y,
        view_hints=ViewHints(width=width, height=height, emphasis="muted"),
    )

def _detail_node(
    node_id: str,
    label: str,
    node_type: str,
    layer: str,
    x: float,
    y: float,
    *,
    width: int = 132,
    height: int = 52,
    ip_ref: str | None = None,
    sw_ref: str | None = None,
    badges: list[str] | None = None,
    ops: OperationSummary | None = None,
    memory: MemoryDescriptor | None = None,
    placement: MemoryPlacement | None = None,
    dma_count: int | None = None,
    shared_resource: bool = False,
    warning: bool = False,
    detail_items: list[str] | None = None,
) -> NodeElement:
    return _n(
        node_id,
        label,
        node_type,
        layer,
        x,
        y,
        ip_ref=ip_ref,
        sw_ref=sw_ref,
        summary_badges=["task"],
        capability_badges=badges or [],
        active_operations=ops,
        memory=memory,
        placement=placement,
        dma_count=dma_count,
        shared_resource=shared_resource,
        warning=warning,
        detail_items=detail_items or [],
        view_hints=ViewHints(width=width, height=height),
    )

def _detail_buffer(
    graph: CanonicalScenarioGraph,
    node_id: str,
    label: str,
    buffer_ref: str,
    x: float,
    y: float,
    tokens: dict[str, str],
    *,
    width: int = 190,
    height: int = 58,
) -> NodeElement:
    memory = _buffer_memory_from_spec(graph, buffer_ref, tokens)
    placement = _buffer_placement_from_spec(graph, buffer_ref)
    suffix: list[str] = []
    if memory:
        fmt = memory.format or "buffer"
        size = f"{memory.width}x{memory.height}" if memory.width and memory.height else None
        suffix.extend([part for part in (fmt, size, memory.compression) if part])
    if placement and placement.llc_allocated:
        suffix.append(f"LLC {placement.llc_allocation_mb or '?'}MB")
    return _detail_node(
        node_id,
        f"{label}\n" + " | ".join(suffix),
        "buffer",
        "memory",
        x,
        y,
        width=width,
        height=height,
        memory=memory,
        placement=placement,
        detail_items=_buffer_detail_items(graph, buffer_ref),
    )

def _project_level2_reference(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    normalized = str(expand or "").strip().lower()
    if normalized in {"camera", "cam", "csis", "isp", "camera-pipeline", "camera_pipeline"}:
        return _project_level2_camera(graph, "camera")
    if normalized in {"video", "codec", "mfc", "encode", "encoder"}:
        return _project_level2_video(graph, "video")
    if normalized in {"display", "dpu", "decon"}:
        return _project_level2_display(graph, "display")
    return None

def _project_level2_camera(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    sensor = tokens["sensor_full"]
    record = tokens["record_out"]
    preview = tokens["preview_out"]
    fps = tokens["fps"]

    nodes = [
        _group_box("l2cam-grp-sw", "SW Control / Task Scheduling", 245, 220, 360, 320),
        _group_box("l2cam-grp-csis", "Camera Frontend (CSIS)", 705, 220, 430, 320),
        _group_box("l2cam-grp-isp", "ISP Processing Core", 680, 620, 760, 620),
        _group_box("l2cam-grp-dma", "DMA / SystemMMU / Memory Ports", 1160, 620, 420, 620),
        _group_box("l2cam-grp-memory", "Frame Buffers / Memory Placement", 710, 1135, 900, 250),
        _group_box("l2cam-grp-downstream", "Downstream Consumers", 1190, 1135, 360, 250),
        _detail_node("l2cam-app", "Camera App", "sw", "app", 160, 115, width=150, height=48),
        _detail_node("l2cam-fw", "CameraService", "sw", "framework", 160, 185, width=165, height=48),
        _detail_node("l2cam-hal", "Camera HAL", "sw", "hal", 160, 255, width=150, height=48),
        _detail_node("l2cam-v4l2", "V4L2 Camera Driver", "sw", "kernel", 160, 335, width=180, height=50),
        _detail_node("l2cam-postirta", "postIRTA\nCPU_MID_Cluster", "sw", "kernel", 330, 255, width=170, height=54),
        _detail_node("l2cam-postirta2", "postIRTA2\nCPU_MID_Cluster", "sw", "kernel", 330, 335, width=170, height=54),
        _detail_node("l2cam-sensor", f"Sensor\n{sensor}@{fps}fps", "ip", "hw", 560, 115, width=150, height=58),
        _detail_node("l2cam-csislink", f"CSIS_LINK\n{sensor}", "submodule", "hw", 705, 195, width=150, height=54, ip_ref="ip-csis-v8"),
        _detail_node("l2cam-csis", f"CSIS\n{sensor}", "submodule", "hw", 705, 285, width=150, height=54, ip_ref="ip-csis-v8"),
        _detail_node("l2cam-pdp", f"PDP\n{sensor}", "submodule", "hw", 400, 455, width=136, height=52),
        _detail_node("l2cam-prep", f"PREP\n{sensor}", "submodule", "hw", 580, 455, width=136, height=52),
        _detail_node(
            "l2cam-cstat",
            f"CSTAT\n{sensor}->{record}",
            "submodule",
            "hw",
            760,
            455,
            width=190,
            height=64,
            badges=["CROP", "SCALE"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _detail_node("l2cam-byrp", f"BYRP\n{sensor}", "submodule", "hw", 400, 575, width=136, height=52),
        _detail_node("l2cam-rgbp", f"RGBP\n{sensor}", "submodule", "hw", 580, 575, width=136, height=52),
        _detail_node(
            "l2cam-mlsc",
            f"MLSC\n{sensor}->{record}",
            "submodule",
            "hw",
            760,
            575,
            width=190,
            height=64,
            badges=["SCALE", "CSC"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record, colorspace_convert="RAW->YUV"),
        ),
        _detail_node("l2cam-mtnr1", f"MTNR1\n{preview}", "submodule", "hw", 400, 725, width=136, height=52),
        _detail_node("l2cam-mtnr0", f"MTNR0\n{record}", "submodule", "hw", 580, 725, width=136, height=52),
        _detail_node("l2cam-msnr", f"MSNR\n{record}", "submodule", "hw", 760, 725, width=136, height=52),
        _detail_node("l2cam-yuvp", f"YUVP\n{record}", "submodule", "hw", 580, 865, width=136, height=52),
        _detail_node(
            "l2cam-mcsc",
            f"MCSC\n{record}/{preview}",
            "submodule",
            "hw",
            760,
            865,
            width=190,
            height=64,
            badges=["SCALE"],
            ops=OperationSummary(scale=True, scale_from=record, scale_to=preview),
        ),
        _detail_node("l2cam-dma-csis", "CSIS_WDMA\nBAYER_PACKED 12b", "dma_channel", "hw", 1070, 340, width=190, height=54, dma_count=1),
        _detail_node("l2cam-dma-comp", "COMP_RD0_RDMA\nRAW COMP read", "dma_channel", "hw", 1240, 465, width=190, height=54, dma_count=1),
        _detail_node("l2cam-dma-p0", "P0_WDMA\nRecord path", "dma_channel", "hw", 1070, 720, width=160, height=54, dma_count=1),
        _detail_node("l2cam-dma-p1", "P1_WDMA\nPreview path", "dma_channel", "hw", 1240, 720, width=160, height=54, dma_count=1),
        _detail_node("l2cam-sysmmu", "SYSMMU_CAM\nshared S2MPU path", "sysmmu", "hw", 1160, 895, width=200, height=58, shared_resource=True),
        _detail_buffer(graph, "l2cam-rawbuf", "RAW Bayer", "RAW_BAYER_MAIN", 430, 1125, tokens),
        _detail_buffer(graph, "l2cam-recbuf", "Encoder Input", "RECORD_BUF", 710, 1125, tokens),
        _detail_buffer(graph, "l2cam-prevbuf", "Preview", "PREVIEW_BUF", 990, 1125, tokens),
        _detail_node("l2cam-mfc", f"MFC\n{record}", "ip", "hw", 1120, 1125, width=130, height=58, ip_ref="ip-mfc-v14"),
        _detail_node("l2cam-dpu", f"DPU\n{preview}", "ip", "hw", 1280, 1125, width=130, height=58, ip_ref="ip-dpu-v9"),
    ]
    edges = [
        _e("l2cam-sw-0", "l2cam-app", "l2cam-fw", "control", label="SW"),
        _e("l2cam-sw-1", "l2cam-fw", "l2cam-hal", "control", label="Camera API"),
        _e("l2cam-sw-2", "l2cam-hal", "l2cam-v4l2", "control", label="V4L2"),
        _e("l2cam-sw-3", "l2cam-v4l2", "l2cam-csis", "control", label="subdev routing"),
        _e("l2cam-sw-4", "l2cam-mlsc", "l2cam-postirta", "control", label="SW"),
        _e("l2cam-sw-5", "l2cam-postirta", "l2cam-postirta2", "control", label="SW"),
        _e("l2cam-sw-6", "l2cam-postirta2", "l2cam-mtnr1", "control", label="TNR schedule"),
        _e("l2cam-sw-7", "l2cam-postirta2", "l2cam-mtnr0", "control", label="TNR schedule"),
        _e("l2cam-otf-0", "l2cam-sensor", "l2cam-csislink", "OTF", label="MIPI CSI"),
        _e("l2cam-otf-1", "l2cam-csislink", "l2cam-csis", "OTF", label="LINK->NFI_DEC"),
        _e("l2cam-otf-2", "l2cam-csis", "l2cam-pdp", "OTF", label="IBUF->REORDER"),
        _e("l2cam-otf-3", "l2cam-csis", "l2cam-prep", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-4", "l2cam-prep", "l2cam-cstat", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-m2m-0", "l2cam-csis", "l2cam-dma-csis", "M2M", label=f"CSIS_WDMA | {sensor}", buffer_ref="RAW_BAYER_MAIN", memory=_buffer_memory_from_spec(graph, "RAW_BAYER_MAIN", tokens), placement=_buffer_placement_from_spec(graph, "RAW_BAYER_MAIN")),
        _e("l2cam-m2m-1", "l2cam-dma-csis", "l2cam-rawbuf", "M2M", label="write RAW"),
        _e("l2cam-m2m-2", "l2cam-rawbuf", "l2cam-dma-comp", "M2M", label="COMP_RD0_RDMA"),
        _e("l2cam-m2m-3", "l2cam-dma-comp", "l2cam-byrp", "M2M", label="read RAW COMP"),
        _e("l2cam-otf-5", "l2cam-byrp", "l2cam-rgbp", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-6", "l2cam-rgbp", "l2cam-mlsc", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-7", "l2cam-mtnr1", "l2cam-msnr", "OTF", label="L1/L2/L3/G4"),
        _e("l2cam-otf-8", "l2cam-mtnr0", "l2cam-msnr", "OTF", label="L0"),
        _e("l2cam-otf-9", "l2cam-msnr", "l2cam-yuvp", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-otf-10", "l2cam-yuvp", "l2cam-mcsc", "OTF", label="COUTFIFO->CINFIFO"),
        _e("l2cam-m2m-4", "l2cam-mcsc", "l2cam-dma-p0", "M2M", label=f"P0_WDMA | {record} | YUV420 | 10b", buffer_ref="RECORD_BUF", memory=_buffer_memory_from_spec(graph, "RECORD_BUF", tokens), placement=_buffer_placement_from_spec(graph, "RECORD_BUF")),
        _e("l2cam-m2m-5", "l2cam-mcsc", "l2cam-dma-p1", "M2M", label=f"P1_WDMA | {preview} | YUV420 | 10b", buffer_ref="PREVIEW_BUF", memory=_buffer_memory_from_spec(graph, "PREVIEW_BUF", tokens), placement=_buffer_placement_from_spec(graph, "PREVIEW_BUF")),
        _e("l2cam-m2m-6", "l2cam-dma-p0", "l2cam-sysmmu", "M2M", label="SMMU translate"),
        _e("l2cam-m2m-7", "l2cam-dma-p1", "l2cam-sysmmu", "M2M", label="SMMU translate"),
        _e("l2cam-m2m-8", "l2cam-sysmmu", "l2cam-recbuf", "M2M", label="write record"),
        _e("l2cam-m2m-9", "l2cam-sysmmu", "l2cam-prevbuf", "M2M", label="write preview"),
        _e("l2cam-m2m-10", "l2cam-recbuf", "l2cam-mfc", "M2M", label="encoder input"),
        _e("l2cam-m2m-11", "l2cam-prevbuf", "l2cam-dpu", "M2M", label="display input"),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:camera",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1380, "canvas_h": 1290, "layout": "level2-camera-detail", "expand": expand},
    )

def _project_level2_video(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    record = tokens["record_out"]
    codec = tokens["codec"]
    nodes = [
        _group_box("l2vid-grp-sw", "SW Encode Stack", 260, 220, 420, 330),
        _group_box("l2vid-grp-mfc", "MFC Hardware Pipeline", 760, 260, 560, 420),
        _group_box("l2vid-grp-memory", "DMA / SystemMMU / Bitstream Memory", 760, 720, 760, 300),
        _detail_node("l2vid-app", "Recorder App", "sw", "app", 150, 115, width=160, height=48),
        _detail_node("l2vid-fw", "MediaRecorder", "sw", "framework", 150, 195, width=170, height=48),
        _detail_node("l2vid-hal", "Codec2 HAL", "sw", "hal", 150, 275, width=155, height=48),
        _detail_node("l2vid-driver", "MFC Driver", "sw", "kernel", 150, 355, width=155, height=48),
        _detail_node("l2vid-mfc", f"MFC Frontend\n{codec}", "ip", "hw", 560, 165, width=160, height=60, ip_ref="ip-mfc-v14", badges=[codec, "ENC"]),
        _detail_node("l2vid-rdma", f"MFC_RDMA\n{record}", "dma_channel", "hw", 760, 165, width=155, height=56, dma_count=1),
        _detail_node("l2vid-core", f"MFC_CORE\n{codec} encode", "submodule", "hw", 760, 315, width=170, height=62, ip_ref="ip-mfc-v14"),
        _detail_node("l2vid-wdma", "MFC_WDMA\nbitstream write", "dma_channel", "hw", 960, 315, width=170, height=56, dma_count=1),
        _detail_node("l2vid-sysmmu", "SYSMMU_MFC\nLLC-aware mapping", "sysmmu", "hw", 760, 585, width=210, height=60, shared_resource=True),
        _detail_buffer(graph, "l2vid-recbuf", "Encoder Input", "RECORD_BUF", 520, 720, tokens, width=210),
        _detail_buffer(graph, "l2vid-bitstream", "Encoded Bitstream", "ENCODED_BITSTREAM", 880, 720, tokens, width=230),
    ]
    edges = [
        _e("l2vid-sw-0", "l2vid-app", "l2vid-fw", "control", label="Media API"),
        _e("l2vid-sw-1", "l2vid-fw", "l2vid-hal", "control", label="Codec2"),
        _e("l2vid-sw-2", "l2vid-hal", "l2vid-driver", "control", label="ioctl / queue"),
        _e("l2vid-sw-3", "l2vid-driver", "l2vid-mfc", "control", label="register programming"),
        _e("l2vid-m2m-0", "l2vid-recbuf", "l2vid-rdma", "M2M", label=f"read {record} YUV420", buffer_ref="RECORD_BUF", memory=_buffer_memory_from_spec(graph, "RECORD_BUF", tokens), placement=_buffer_placement_from_spec(graph, "RECORD_BUF")),
        _e("l2vid-otf-0", "l2vid-rdma", "l2vid-mfc", "OTF", label="input stream"),
        _e("l2vid-otf-1", "l2vid-mfc", "l2vid-core", "OTF", label="encode pipe"),
        _e("l2vid-otf-2", "l2vid-core", "l2vid-wdma", "OTF", label="coded output"),
        _e("l2vid-m2m-1", "l2vid-wdma", "l2vid-sysmmu", "M2M", label="SMMU translate"),
        _e("l2vid-m2m-2", "l2vid-sysmmu", "l2vid-bitstream", "M2M", label="write bitstream", buffer_ref="ENCODED_BITSTREAM", memory=_buffer_memory_from_spec(graph, "ENCODED_BITSTREAM", tokens), placement=_buffer_placement_from_spec(graph, "ENCODED_BITSTREAM")),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:video",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 920, "layout": "level2-video-detail", "expand": expand},
    )

def _project_level2_display(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    tokens = _reference_sizes(graph)
    preview = tokens["preview_out"]
    nodes = [
        _group_box("l2disp-grp-sw", "Display SW Stack", 260, 220, 420, 330),
        _group_box("l2disp-grp-dpu", "DPU / DECON / Panel Path", 760, 270, 560, 440),
        _group_box("l2disp-grp-memory", "DMA / SystemMMU / Display Buffer", 760, 750, 760, 300),
        _detail_node("l2disp-sf", "SurfaceFlinger", "sw", "framework", 150, 135, width=170, height=48),
        _detail_node("l2disp-hwc", "HW Composer", "sw", "hal", 150, 225, width=170, height=48),
        _detail_node("l2disp-drm", "DRM / KMS", "sw", "kernel", 150, 315, width=150, height=48),
        _detail_node("l2disp-rdma", f"DPU_RDMA\n{preview}", "dma_channel", "hw", 560, 210, width=160, height=56, dma_count=1),
        _detail_node("l2disp-decon", "DECON\ncompose", "submodule", "hw", 760, 210, width=160, height=56, ops=OperationSummary(compose=True)),
        _detail_node("l2disp-dpu", f"DPU\n{preview}", "ip", "hw", 760, 370, width=150, height=58, ip_ref="ip-dpu-v9", ops=OperationSummary(compose=True)),
        _detail_node("l2disp-dsi", "DSI / Panel\nscanout", "submodule", "hw", 960, 370, width=160, height=58),
        _detail_node("l2disp-sysmmu", "SYSMMU_DPU\nread path", "sysmmu", "hw", 760, 610, width=200, height=58, shared_resource=True),
        _detail_buffer(graph, "l2disp-prevbuf", "Preview Buffer", "PREVIEW_BUF", 560, 750, tokens, width=220),
        _detail_node("l2disp-panel", "Display Panel\nscanout endpoint", "ip", "hw", 960, 750, width=190, height=58),
    ]
    edges = [
        _e("l2disp-sw-0", "l2disp-sf", "l2disp-hwc", "control", label="composition request"),
        _e("l2disp-sw-1", "l2disp-hwc", "l2disp-drm", "control", label="atomic commit"),
        _e("l2disp-sw-2", "l2disp-drm", "l2disp-dpu", "control", label="KMS"),
        _e("l2disp-m2m-0", "l2disp-prevbuf", "l2disp-sysmmu", "M2M", label="read preview buffer", buffer_ref="PREVIEW_BUF", memory=_buffer_memory_from_spec(graph, "PREVIEW_BUF", tokens), placement=_buffer_placement_from_spec(graph, "PREVIEW_BUF")),
        _e("l2disp-m2m-1", "l2disp-sysmmu", "l2disp-rdma", "M2M", label="translated read"),
        _e("l2disp-otf-0", "l2disp-rdma", "l2disp-decon", "OTF", label="pixel stream"),
        _e("l2disp-otf-1", "l2disp-decon", "l2disp-dpu", "OTF", label="compose"),
        _e("l2disp-otf-2", "l2disp-dpu", "l2disp-dsi", "OTF", label="DSI"),
        _e("l2disp-otf-3", "l2disp-dsi", "l2disp-panel", "OTF", label="scanout"),
    ]
    return _response(
        graph=graph,
        level=2,
        mode="drilldown:display",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 950, "layout": "level2-display-detail", "expand": expand},
    )

def _project_reference_task_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    """Reference task DAG shaped after the legacy projectA FHD30 topology view.

    The current canonical fixture is intentionally shallow, so this projection
    expands a camera-recording usecase into the task-level chain the legacy
    viewer made useful: HW tasks, SW/CPU tasks, OTF links, and M2M buffer edges.
    """
    from_fixture = _project_task_graph_from_fixture(graph, level=level, mode="topology")
    if from_fixture is not None:
        return from_fixture

    sz = _reference_sizes(graph)
    sensor = sz["sensor"]
    record = sz["record"]
    preview = sz["preview"]
    fps = sz["fps"]
    codec = sz["codec"]

    nodes = [
        _ref_task_node("t_sensor", f"t_sensor\n(Sensor)\n{sensor}@{fps}", 520, 70, width=150, height=60),
        _ref_task_node("t_csislink", f"t_csislink\n(CSIS_LINK)\n{sensor}", 520, 170),
        _ref_task_node("t_csis", f"t_csis\n(CSIS)\n{sensor}", 520, 270, ip_ref="ip-csis-v8"),
        _ref_task_node("t_pdp", f"t_pdp\n(PDP)\n{sensor}", 300, 390),
        _ref_task_node("t_prep", f"t_prep\n(PREP)\n{sensor}", 705, 390),
        _ref_task_node(
            "t_cstat",
            f"t_cstat\n(CSTAT)\n{sensor}->{record}",
            705,
            520,
            width=184,
            height=66,
            badges=["S", "C"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_byrp", f"t_byrp\n(BYRP)\n{sensor}", 520, 405),
        _ref_task_node("t_rgbp", f"t_rgbp\n(RGBP)\n{sensor}", 520, 520),
        _ref_task_node(
            "t_mlsc",
            f"t_mlsc\n(MLSC)\n{sensor}->{record}",
            520,
            660,
            width=184,
            height=66,
            badges=["S", "C"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_postIRTA", "t_postIRTA\n(CPU_MID_Cluster)", 520, 805, layer="kernel", width=180, height=52),
        _ref_task_node("t_postIRTA2", "t_postIRTA2\n(CPU_MID_Cluster)", 520, 925, layer="kernel", width=180, height=52),
        _ref_task_node("t_mtnr1", f"t_mtnr1\n(MTNR1)\n{preview}", 390, 1060),
        _ref_task_node("t_mtnr0", f"t_mtnr0\n(MTNR0)\n{record}", 650, 1060),
        _ref_task_node("t_msnr", f"t_msnr\n(MSNR)\n{record}", 520, 1205),
        _ref_task_node("t_yuvp", f"t_yuvp\n(YUVP)\n{record}", 520, 1340),
        _ref_task_node("t_mcsc", f"t_mcsc\n(MCSC)\n{record}", 520, 1480, ops=OperationSummary(scale=True, scale_to=record)),
        _ref_task_node("t_codec2", "t_codec2\n(CPU_MID_Cluster)", 430, 1640, layer="kernel", width=180, height=52),
        _ref_task_node("t_hw_composer", "t_hw_composer\n(CPU_MID_Cluster)", 650, 1640, layer="kernel", width=190, height=52),
        _ref_task_node("t_mfc", f"t_mfc\n(MFC)\n{record}", 430, 1790, ip_ref="ip-mfc-v14"),
        _ref_task_node("t_dpu", f"t_dpu\n(DPU)\n{preview}", 650, 1790, ip_ref="ip-dpu-v9"),
    ]

    edges = [
        _e("eo-0", "t_sensor", "t_csislink", "OTF", label="OTF"),
        _e("eo-1", "t_csislink", "t_csis", "OTF", label="OTF: LINK->NFI_DEC"),
        _e("eo-2", "t_csis", "t_pdp", "OTF", label="OTF: IBUF->REORDER"),
        _e("eo-3", "t_csis", "t_prep", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("em-4", "t_csis", "t_byrp", "M2M", label=f"CSIS_WDMA->COMP_RD0_RDMA | {sensor} | BAYER_PACKED | 12bit | COMP"),
        _e("eo-5", "t_prep", "t_cstat", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-6", "t_byrp", "t_rgbp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-7", "t_rgbp", "t_mlsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("esw-8", "t_mlsc", "t_postIRTA", "control", label="SW"),
        _e("esw-9", "t_postIRTA", "t_postIRTA2", "control", label="SW"),
        _e("esw-10", "t_postIRTA2", "t_mtnr1", "control", label="SW"),
        _e("esw-11", "t_postIRTA2", "t_mtnr0", "control", label="SW"),
        _e("eo-12", "t_mtnr0", "t_msnr", "OTF", label="OTF: L0_COUTFIFO->L0_CINFIFO"),
        _e("eo-13", "t_mtnr1", "t_msnr", "OTF", label="OTF: L1/L2/L3/G4 COUTFIFO->CINFIFO"),
        _e("eo-14", "t_msnr", "t_yuvp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("eo-15", "t_yuvp", "t_mcsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("em-16", "t_mcsc", "t_codec2", "M2M", label=f"P0_WDMA->input | {record} | YUV420 | 10bit"),
        _e("em-17", "t_mcsc", "t_hw_composer", "M2M", label=f"P1_WDMA->input | {preview} | YUV420 | 10bit"),
        _e("esw-18", "t_codec2", "t_mfc", "control", label="SW"),
        _e("esw-19", "t_hw_composer", "t_dpu", "control", label="SW"),
    ]

    return _response(
        graph=graph,
        level=level,
        mode="task-topology",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1100, "canvas_h": 1880, "layout": "task-topology"},
    )

def _project_reference_level1(graph: CanonicalScenarioGraph) -> ViewResponse:
    """Reference Level 1 IP detail view shaped after the legacy grouped DAG."""
    from_fixture = _project_level1_from_fixture(graph)
    if from_fixture is not None:
        return from_fixture

    sz = _reference_sizes(graph)
    sensor = sz["sensor"]
    record = sz["record"]
    preview = sz["preview"]
    fps = sz["fps"]

    nodes = [
        _group_box("grp-sensor", "Sensor", 520, 85, 180, 100),
        _group_box("grp-isp", "ISP", 580, 470, 900, 620),
        _group_box("grp-cpu", "CPU", 580, 980, 520, 210),
        _group_box("grp-codec", "CODEC", 460, 1250, 190, 120),
        _group_box("grp-dpu", "DPU", 700, 1250, 190, 120),
        _ref_task_node("t_sensor", f"Sensor\n{sensor}@{fps}fps", 520, 110, width=136, height=56),
        _ref_task_node("t_csislink", f"CSIS_LINK\n{sensor}", 520, 255, width=126, height=50, ip_ref="ip-csis-v8"),
        _ref_task_node("t_csis", f"CSIS\n{sensor}", 520, 350, width=126, height=50, ip_ref="ip-csis-v8"),
        _ref_task_node("t_pdp", f"PDP\n{sensor}", 305, 470, width=126, height=50),
        _ref_task_node("t_prep", f"PREP\n{sensor}", 735, 470, width=126, height=50),
        _ref_task_node(
            "t_cstat",
            f"CSTAT\n{sensor}->{record}",
            735,
            590,
            width=170,
            height=64,
            badges=["S", "C"],
            ops=OperationSummary(crop=True, scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_byrp", f"BYRP\n{sensor}", 520, 470, width=126, height=50),
        _ref_task_node("t_rgbp", f"RGBP\n{sensor}", 520, 590, width=126, height=50),
        _ref_task_node(
            "t_mlsc",
            f"MLSC\n{sensor}->{record}",
            520,
            720,
            width=170,
            height=64,
            badges=["S", "C"],
            ops=OperationSummary(scale=True, scale_from=sensor, scale_to=record),
        ),
        _ref_task_node("t_mtnr1", f"MTNR1\n{preview}", 835, 280, width=126, height=50),
        _ref_task_node("t_mtnr0", f"MTNR0\n{record}", 1015, 280, width=126, height=50),
        _ref_task_node("t_msnr", f"MSNR\n{record}", 925, 430, width=126, height=50),
        _ref_task_node("t_yuvp", f"YUVP\n{record}", 925, 590, width=126, height=50),
        _ref_task_node("t_mcsc", f"MCSC\n{record}", 925, 710, width=126, height=50),
        _ref_task_node("t_postIRTA", "CPU_MID_Cluster", 390, 955, layer="kernel", width=150, height=46),
        _ref_task_node("t_postIRTA2", "CPU_MID_Cluster", 390, 1070, layer="kernel", width=150, height=46),
        _ref_task_node("t_codec2", "CPU_MID_Cluster", 580, 955, layer="kernel", width=150, height=46),
        _ref_task_node("t_hw_composer", "CPU_MID_Cluster", 770, 955, layer="kernel", width=160, height=46),
        _ref_task_node("t_mfc", f"MFC\n{record}", 460, 1305, ip_ref="ip-mfc-v14", width=130, height=58),
        _ref_task_node("t_dpu", f"DPU\n{preview}", 700, 1305, ip_ref="ip-dpu-v9", width=130, height=58),
    ]

    edges = [
        _e("l1-eo-0", "t_sensor", "t_csislink", "OTF", label="OTF"),
        _e("l1-eo-1", "t_csislink", "t_csis", "OTF", label="OTF: LINK->NFI_DEC"),
        _e("l1-eo-2", "t_csis", "t_pdp", "OTF", label="OTF: IBUF->REORDER"),
        _e("l1-eo-3", "t_csis", "t_prep", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-em-4", "t_csis", "t_byrp", "M2M", label=f"CSIS_WDMA->COMP_RD0_RDMA | {sensor} | BAYER_PACKED | 12bit | COMP"),
        _e("l1-eo-5", "t_prep", "t_cstat", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-6", "t_byrp", "t_rgbp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-7", "t_rgbp", "t_mlsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-esw-8", "t_mlsc", "t_postIRTA", "control", label="SW"),
        _e("l1-esw-9", "t_postIRTA", "t_postIRTA2", "control", label="SW"),
        _e("l1-esw-10", "t_postIRTA2", "t_mtnr1", "control", label="SW"),
        _e("l1-esw-11", "t_postIRTA2", "t_mtnr0", "control", label="SW"),
        _e("l1-eo-12", "t_mtnr0", "t_msnr", "OTF", label="OTF: L0_COUTFIFO->L0_CINFIFO"),
        _e("l1-eo-13", "t_mtnr1", "t_msnr", "OTF", label="OTF: L1/L2/L3/G4 COUTFIFO->CINFIFO"),
        _e("l1-eo-14", "t_msnr", "t_yuvp", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-eo-15", "t_yuvp", "t_mcsc", "OTF", label="OTF: COUTFIFO->CINFIFO"),
        _e("l1-em-16", "t_mcsc", "t_codec2", "M2M", label=f"P0_WDMA->input | {record} | YUV420 | 10bit"),
        _e("l1-em-17", "t_mcsc", "t_hw_composer", "M2M", label=f"P1_WDMA->input | {preview} | YUV420 | 10bit"),
        _e("l1-esw-18", "t_codec2", "t_mfc", "control", label="SW"),
        _e("l1-esw-19", "t_hw_composer", "t_dpu", "control", label="SW"),
    ]

    return _response(
        graph=graph,
        level=1,
        mode="level1-ip-detail",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 1180, "canvas_h": 1370, "layout": "level1-reference"},
    )



def project_reference_level1(graph: CanonicalScenarioGraph) -> ViewResponse:
    return _project_reference_level1(graph)


def project_reference_task_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    return _project_reference_task_topology(graph, level)


def project_level2_reference(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    return _project_level2_reference(graph, expand)
