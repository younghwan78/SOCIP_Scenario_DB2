"""View projection service.

build_canonical_graph() → project_level0() → ViewResponse

Sample data matches the "Video Recording — FHD 30fps" scenario from the
design draft. Real DB integration is wired via the FastAPI router; the
dashboard can also call this module directly without an HTTP round-trip.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from scenario_db.api.schemas.view import (
    EdgeData, EdgeElement, EdgeSimOverlay, MemoryDescriptor, MemoryPlacement,
    Level0MetricBreakdown, NodeData, NodeElement, OperationSummary, ResourceMetricSummary, RiskCard,
    SimOverlay, ViewHints, ViewResponse, ViewSummary,
)
from scenario_db.db.repositories.scenario_graph import (
    CanonicalScenarioGraph,
    load_base_canonical_graph,
    load_canonical_graph,
)
from scenario_db.review_gate.engine import run_review_gate
from scenario_db.view.level0 import (
    Level0ProjectionDeps,
    project_architecture as _level0_project_architecture,
    project_topology as _level0_project_topology,
)
from scenario_db.view.level0_v2 import build_resource_overview
from scenario_db.view.layout import (
    BG_CENTER_X, BG_WIDTH, CANVAS_H, CANVAS_W,
    LANE_H, LANE_LABEL_W, LANE_Y, LANE_DISPLAY_NAMES,
    NODE_H, NODE_W, STAGE_HEADER_H, STAGE_X,
)


# ---------------------------------------------------------------------------
# Sample scenario — Camera Recording FHD 30fps (matches design image)
# ---------------------------------------------------------------------------

def _n(nid: str, label: str, ntype: str, layer: str,
       x: float, y: float, **kwargs) -> NodeElement:
    data = NodeData(id=nid, label=label, type=ntype, layer=layer, **kwargs)
    return NodeElement(data=data, position={"x": x, "y": y})


def _e(eid: str, src: str, tgt: str, flow_type: str, **kwargs) -> EdgeElement:
    data = EdgeData(id=eid, source=src, target=tgt, flow_type=flow_type, **kwargs)
    return EdgeElement(data=data)


def build_sample_level0() -> ViewResponse:
    """Return a hardcoded Level 0 ViewResponse for the FHD30 demo scenario."""
    ly = LANE_Y

    # ── Functional nodes ──────────────────────────────────────────────────
    nodes: list[NodeElement] = [
        # App lane
        _n("app-camera",   "Camera App",    "sw", "app",       210, ly["app"],
           view_hints=ViewHints(lane="app", stage="capture", order=0)),
        _n("app-recorder", "Recorder App",  "sw", "app",       510, ly["app"],
           view_hints=ViewHints(lane="app", stage="processing", order=0)),

        # Framework lane
        _n("fw-cam-svc",   "CameraService",  "sw", "framework", 210, ly["framework"],
           view_hints=ViewHints(lane="framework", stage="capture", order=0)),
        _n("fw-media-rec", "MediaRecorder",  "sw", "framework", 510, ly["framework"],
           view_hints=ViewHints(lane="framework", stage="processing", order=0)),
        _n("fw-codec-fw",  "MediaCodec FW",  "sw", "framework", 790, ly["framework"],
           view_hints=ViewHints(lane="framework", stage="encode", order=0)),

        # HAL lane
        _n("hal-camera",  "Camera HAL",  "sw", "hal", 210, ly["hal"],
           view_hints=ViewHints(lane="hal", stage="capture", order=0)),
        _n("hal-codec2",  "Codec2 HAL",  "sw", "hal", 510, ly["hal"],
           view_hints=ViewHints(lane="hal", stage="processing", order=0)),

        # Kernel lane
        _n("ker-v4l2",   "V4L2 Camera Driver", "sw", "kernel", 210, ly["kernel"],
           view_hints=ViewHints(lane="kernel", stage="capture", order=0)),
        _n("ker-mfc-drv","MFC Driver",         "sw", "kernel", 510, ly["kernel"],
           view_hints=ViewHints(lane="kernel", stage="processing", order=0)),
        _n("ker-ion",    "ION / DMA-BUF",      "sw", "kernel", 790, ly["kernel"],
           view_hints=ViewHints(lane="kernel", stage="encode", order=0)),
        _n("ker-drm",    "DRM / KMS",          "sw", "kernel", 1010, ly["kernel"],
           view_hints=ViewHints(lane="kernel", stage="display", order=0),
           warning=False),

        # HW lane — ISP active scale 4000x3000→1920x1080
        # hw-sensor x=130: min valid = LANE_LABEL_W(80) + NODE_W["ip"](100)/2 = 130
        _n("hw-sensor",  "Sensor",  "ip", "hw", 130, ly["hw"],
           view_hints=ViewHints(lane="hw", stage="capture", order=0, emphasis="primary")),
        _n("hw-csis",    "CSIS",    "ip", "hw", 240, ly["hw"],
           view_hints=ViewHints(lane="hw", stage="capture", order=1)),
        _n("hw-isp",     "ISP",     "ip", "hw", 410, ly["hw"],
           ip_ref="ip-isp-v12",
           capability_badges=["CROP", "SCALE", "HDR10"],
           active_operations=OperationSummary(
               scale=True, scale_from="4000x3000", scale_to="1920x1080",
               crop=True, crop_ratio=0.9,
           ),
           view_hints=ViewHints(lane="hw", stage="processing", order=0, emphasis="primary")),
        _n("hw-mlsc",    "MLSC",    "ip", "hw", 530, ly["hw"],
           view_hints=ViewHints(lane="hw", stage="processing", order=1)),
        _n("hw-mcsc",    "MCSC",    "ip", "hw", 645, ly["hw"],
           view_hints=ViewHints(lane="hw", stage="processing", order=2)),
        _n("hw-mfc",     "MFC",     "ip", "hw", 810, ly["hw"],
           ip_ref="ip-mfc-v14",
           capability_badges=["H.265", "AV1"],
           matched_issues=["iss-LLC-thrashing-0221"],
           warning=True,
           view_hints=ViewHints(lane="hw", stage="encode", order=0, emphasis="risk")),
        _n("hw-dpu",     "DPU",     "ip", "hw", 1010, ly["hw"],
           ip_ref="ip-dpu-v9",
           view_hints=ViewHints(lane="hw", stage="display", order=0)),

        # Buffer (memory) lane
        _n("buf-raw",     "RAW Buffer",           "buffer", "memory", 195, ly["memory"],
           memory=MemoryDescriptor(format="RAW10", bitdepth=10, planes=1,
                                   width=4000, height=3000, fps=30),
           view_hints=ViewHints(lane="memory", stage="capture", order=0)),
        _n("buf-yuv",     "YUV Preview Buffer",   "buffer", "memory", 415, ly["memory"],
           memory=MemoryDescriptor(format="NV12", bitdepth=8, planes=2,
                                   width=1920, height=1080, fps=30),
           view_hints=ViewHints(lane="memory", stage="processing", order=0)),
        _n("buf-enc-in",  "Encoder Input Buffer", "buffer", "memory", 605, ly["memory"],
           memory=MemoryDescriptor(format="NV12", compression="SBWC_v4",
                                   width=1920, height=1080, fps=30),
           placement=MemoryPlacement(llc_allocated=True, llc_allocation_mb=1.0,
                                      llc_policy="dedicated", allocation_owner="MFC"),
           view_hints=ViewHints(lane="memory", stage="processing", order=1)),
        _n("buf-enc-out", "Encoded Bitstream",    "buffer", "memory", 815, ly["memory"],
           memory=MemoryDescriptor(format="H.265", fps=30),
           view_hints=ViewHints(lane="memory", stage="encode", order=0)),
        _n("buf-disp",    "Display Buffer",       "buffer", "memory", 1010, ly["memory"],
           memory=MemoryDescriptor(format="ARGB8888", width=1920, height=1080, fps=30),
           view_hints=ViewHints(lane="memory", stage="display", order=0)),
    ]

    # ── Edges ─────────────────────────────────────────────────────────────
    edges: list[EdgeElement] = [
        # App horizontal (SW/control)
        _e("e-app-h", "app-camera", "app-recorder", "control"),

        # Capture column — vertical SW/control (bidirectional)
        _e("e-cap-app-fw",  "app-camera",   "fw-cam-svc",  "control"),
        _e("e-cap-fw-hal",  "fw-cam-svc",   "hal-camera",  "control"),
        _e("e-cap-hal-ker", "hal-camera",   "ker-v4l2",    "control"),
        _e("e-cap-ker-hw",  "ker-v4l2",     "hw-csis",     "control"),

        # Processing column — vertical SW/control
        _e("e-proc-app-fw",  "app-recorder", "fw-media-rec", "control"),
        _e("e-proc-fw-hal",  "fw-media-rec", "hal-codec2",   "control"),
        _e("e-proc-hal-ker", "hal-codec2",   "ker-mfc-drv",  "control"),
        _e("e-proc-ker-hw",  "ker-mfc-drv",  "hw-mlsc",      "control"),

        # HAL horizontal — vOTF (bidirectional, Camera HAL ↔ Codec2 HAL)
        _e("e-hal-votf",  "hal-camera", "hal-codec2", "vOTF"),
        _e("e-hal-votf-r","hal-codec2", "hal-camera", "vOTF"),

        # Kernel horizontal
        _e("e-ker-otf",  "ker-v4l2",    "ker-mfc-drv", "OTF"),
        _e("e-ker-m2m",  "ker-mfc-drv", "ker-ion",     "M2M"),
        _e("e-ker-sw",   "ker-ion",     "ker-drm",     "control"),

        # HW lane — OTF chain
        _e("e-hw-sen-csis",  "hw-sensor", "hw-csis",  "OTF"),
        _e("e-hw-csis-isp",  "hw-csis",   "hw-isp",   "OTF"),
        _e("e-hw-isp-mlsc",  "hw-isp",    "hw-mlsc",  "OTF"),
        _e("e-hw-mlsc-mcsc", "hw-mlsc",   "hw-mcsc",  "OTF"),
        _e("e-hw-mcsc-mfc",  "hw-mcsc",   "hw-mfc",   "M2M"),
        _e("e-hw-mfc-dpu",   "hw-mfc",    "hw-dpu",   "M2M"),

        # HW → Buffer writes (M2M vertical)
        _e("e-isp-buf-yuv",   "hw-isp",  "buf-yuv",    "M2M"),
        _e("e-mfc-buf-out",   "hw-mfc",  "buf-enc-out", "M2M"),
        _e("e-dpu-buf-disp",  "hw-dpu",  "buf-disp",   "M2M"),

        # Buffer lane — vOTF chain (left to right)
        _e("e-buf-raw-yuv",  "buf-raw",    "buf-yuv",    "vOTF"),
        _e("e-buf-yuv-ein",  "buf-yuv",    "buf-enc-in", "vOTF"),
        _e("e-buf-ein-eout", "buf-enc-in", "buf-enc-out","vOTF"),

        # Risk edge — MFC latency (HW → Kernel crossing)
        _e("e-risk-mfc", "hw-mfc", "ker-mfc-drv", "risk",
           label="Latency > budget"),
    ]

    # ── Summary & risks ───────────────────────────────────────────────────
    summary = ViewSummary(
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        name="Video Recording",
        subtitle="FHD 30fps, 1920x1080",
        period_ms=33.3,
        budget_ms=30.0,
        resolution="1920 x 1080",
        fps=30,
        variant_label="Samsung Exynos",
        notes=(
            "Scenario captured on Exynos reference board. "
            "Measurements via SurfaceFlinger and systrace."
        ),
        captured_at="May 16, 2025 10:42 AM",
    )

    risks: list[RiskCard] = [
        RiskCard(
            id="R1",
            title="MFC Encode Latency High",
            component="MFC",
            description="Encode latency 28.6 ms exceeds budget 30.0 ms (95th percentile)",
            severity="High",
            impact="Budget Overrun",
        ),
        RiskCard(
            id="R2",
            title="DRAM Bandwidth High",
            component="MFC / Memory",
            description="Peak bandwidth 18.2 GB/s near sustained limit 20.0 GB/s",
            severity="Medium",
            impact="Throughput Risk",
        ),
    ]

    return ViewResponse(
        level=0,
        mode="architecture",
        scenario_id="uc-camera-recording",
        variant_id="FHD30-SDR-H265",
        nodes=nodes,
        edges=edges,
        risks=risks,
        summary=summary,
        metadata={"canvas_w": CANVAS_W, "canvas_h": CANVAS_H},
        overlays_available=["issues", "memory-path", "llc-allocation", "compression"],
    )


# ---------------------------------------------------------------------------
# Projection helpers (stubs for DB-backed projection)
# ---------------------------------------------------------------------------

def _deprecated_project_level0(scenario_id: str, variant_id: str, db=None) -> ViewResponse:
    """Project DB data into a Level 0 ViewResponse.

    Falls back to sample data when db is None (dashboard demo mode).
    """
    if db is None:
        return build_sample_level0()
    # TODO: query DB → assemble canonical graph → project to Level 0
    raise NotImplementedError("DB-backed Level 0 projection is Phase C work")


def _deprecated_project_level1(scenario_id: str, variant_id: str, db=None) -> ViewResponse:
    raise NotImplementedError("Level 1 IP DAG projection is Phase C work")


def _deprecated_project_level2(scenario_id: str, variant_id: str, expand: str, db=None) -> ViewResponse:
    raise NotImplementedError("Level 2 composite-IP drill-down is Phase C work")


# ---------------------------------------------------------------------------
# DB-backed projections
# ---------------------------------------------------------------------------

def project_level0(
    scenario_id: str,
    variant_id: str | None,
    db=None,
    mode: str = "architecture",
) -> ViewResponse:
    """Project scenario/variant DB data into Level 0 viewer data."""
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    if mode == "topology":
        if graph.has_topology_overlay:
            return _project_topology(graph, level=0)
        return _project_reference_task_topology(graph, level=0)
    return _project_architecture(graph, level=0)


def project_level1(scenario_id: str, variant_id: str | None, db=None) -> ViewResponse:
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    return _project_reference_level1(graph)


def project_level2(scenario_id: str, variant_id: str | None, expand: str, db=None) -> ViewResponse:
    if db is None:
        return build_sample_level0()
    graph = _load_graph(db, scenario_id, variant_id)
    return _project_drilldown(graph, expand)


def apply_simulation_overlay(view: ViewResponse, evidence) -> ViewResponse:
    """Overlay persisted simulation evidence onto an existing view response."""

    if evidence is None:
        return view
    evidence_id = getattr(evidence, "id", None)
    node_rows = _sim_node_rows(evidence)
    dma_rows = _sim_dma_rows(evidence)

    for node in view.nodes:
        row = _match_node_sim_row(node.data, node_rows)
        if not row:
            continue
        timing = row.get("_timing") or {}
        node.data.sim_overlay = SimOverlay(
            required_clock_mhz=_num(row.get("required_clock_mhz")),
            set_clock_mhz=_num(row.get("set_clock_mhz")),
            set_voltage_mv=_num(row.get("set_voltage_mv")),
            power_mw=_num(row.get("total_power_mw") or row.get("active_power_mw")),
            hw_time_ms=_num(timing.get("hw_time_ms")),
            feasible=bool(row.get("feasible", timing.get("feasible", True))),
            evidence_id=evidence_id,
        )
        _append_sim_node_text(node.data)

    for edge in view.edges:
        rows = _match_edge_dma_rows(edge.data, dma_rows)
        if not rows:
            continue
        bw_mbs = sum(_num(row.get("bw_mbs")) or 0.0 for row in rows)
        bw_power_mw = sum(_num(row.get("bw_power_mw")) or 0.0 for row in rows)
        worst_values = [_num(row.get("bw_mbs_worst")) for row in rows if row.get("bw_mbs_worst") is not None]
        edge.data.sim_overlay = EdgeSimOverlay(
            bw_mbs=bw_mbs,
            bw_power_mw=bw_power_mw,
            bw_mbs_worst=sum(value or 0.0 for value in worst_values) if worst_values else None,
            evidence_id=evidence_id,
        )
        _append_sim_edge_text(edge.data)

    if "simulation" not in view.overlays_available:
        view.overlays_available.append("simulation")
    view.metadata["simulation_evidence_id"] = evidence_id
    _apply_level0_resource_metrics(view, evidence_id, node_rows, dma_rows)
    return view


def _sim_node_rows(evidence) -> list[dict[str, Any]]:
    timing_by_node = {
        str(row.get("node_id")): row
        for row in (getattr(evidence, "timing_breakdown", None) or [])
        if isinstance(row, dict) and row.get("node_id")
    }
    rows: list[dict[str, Any]] = []
    for row in getattr(evidence, "dvfs_breakdown", None) or []:
        if not isinstance(row, dict):
            continue
        merged = dict(row)
        timing = timing_by_node.get(str(row.get("node_id")))
        if timing:
            merged["_timing"] = timing
        rows.append(merged)
    for node_id, timing in timing_by_node.items():
        if not any(str(row.get("node_id")) == node_id for row in rows):
            rows.append({"node_id": node_id, "_timing": timing, **timing})
    return rows


def _sim_dma_rows(evidence) -> list[dict[str, Any]]:
    return [
        row
        for row in (getattr(evidence, "dma_breakdown", None) or [])
        if isinstance(row, dict)
    ]


def _match_node_sim_row(data: NodeData, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    node_text = f"{data.id} {data.label} {data.ip_ref or ''}".lower()
    for row in rows:
        node_id = str(row.get("node_id") or "").lower()
        if node_id and (data.id.lower() == node_id or node_id in node_text):
            return row
    for row in rows:
        ip_ref = str(row.get("ip_ref") or "").lower()
        if ip_ref and data.ip_ref and data.ip_ref.lower() == ip_ref:
            return row
    for row in rows:
        hw_name = str(row.get("hw_name") or "").lower()
        if hw_name and hw_name in node_text:
            return row
    return None


def _match_edge_dma_rows(data: EdgeData, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edge_text = f"{data.id} {data.source} {data.target} {data.producer or ''} {data.consumer or ''} {data.buffer_ref or ''}".lower()
    matched = [
        row
        for row in rows
        if (
            (node_id := str(row.get("node_id") or "").lower())
            and node_id in edge_text
        )
        or (
            (hw_name := str(row.get("hw_name") or "").lower())
            and hw_name in edge_text
        )
    ]
    if matched:
        return matched
    # Architecture summary edges often collapse resource groups. Attach DMA rows
    # to M2M edges only when there is no precise node match.
    if data.flow_type == "M2M" and rows:
        return rows
    return []


def _apply_level0_resource_metrics(
    view: ViewResponse,
    evidence_id: str | None,
    node_rows: list[dict[str, Any]],
    dma_rows: list[dict[str, Any]],
) -> None:
    overview = view.level0_resource_overview
    if overview is None:
        return

    for row in overview.rows:
        node_row = _match_resource_node_row(row.node_id, row.label, node_rows)
        matched_dma = _match_resource_dma_rows(row.node_id, row.label, row.buffer_refs, dma_rows)
        if not node_row and not matched_dma:
            continue
        timing = (node_row or {}).get("_timing") or {}
        bw_total = sum(_num(item.get("bw_mbs")) or 0.0 for item in matched_dma)
        read_total = _sum_dma_direction(matched_dma, "read")
        write_total = _sum_dma_direction(matched_dma, "write")
        row.metrics = ResourceMetricSummary(
            power_mw=_num((node_row or {}).get("total_power_mw") or (node_row or {}).get("active_power_mw")),
            bw_read_mbs=read_total,
            bw_write_mbs=write_total,
            bw_total_mbs=bw_total if matched_dma else None,
            hw_time_ms=_num(timing.get("hw_time_ms") or (node_row or {}).get("hw_time_ms")),
            evidence_id=evidence_id,
        )

    _refresh_level0_metric_breakdown(overview)


def _match_resource_node_row(node_id: str, label: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    node_text = f"{node_id} {label}".lower()
    for row in rows:
        candidate = str(row.get("node_id") or "").lower()
        if candidate and (candidate == node_id.lower() or candidate in node_text):
            return row
    for row in rows:
        hw_name = str(row.get("hw_name") or "").lower()
        if hw_name and hw_name in node_text:
            return row
    return None


def _match_resource_dma_rows(
    node_id: str,
    label: str,
    buffer_refs: list[str],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = f"{node_id} {label} {' '.join(buffer_refs)}".lower()
    matched = []
    for row in rows:
        candidate = str(row.get("node_id") or "").lower()
        hw_name = str(row.get("hw_name") or "").lower()
        buffer_ref = str(row.get("buffer_ref") or row.get("buffer") or "").lower()
        if (candidate and (candidate == node_id.lower() or candidate in text)) or (hw_name and hw_name in text):
            matched.append(row)
            continue
        if buffer_ref and buffer_ref in {ref.lower() for ref in buffer_refs}:
            matched.append(row)
    return matched


def _sum_dma_direction(rows: list[dict[str, Any]], direction: str) -> float | None:
    selected = [
        _num(row.get("bw_mbs")) or 0.0
        for row in rows
        if str(row.get("direction") or "").lower() == direction
    ]
    return sum(selected) if selected else None


def _refresh_level0_metric_breakdown(overview) -> None:
    aggregates: dict[str, dict[str, float]] = defaultdict(lambda: {"power": 0.0, "bw": 0.0, "time": 0.0})
    has_value: dict[str, dict[str, bool]] = defaultdict(lambda: {"power": False, "bw": False, "time": False})
    counts: dict[str, int] = defaultdict(int)
    warnings: dict[str, int] = defaultdict(int)
    for row in overview.rows:
        counts[row.subsystem] += 1
        if row.status in {"warning", "blocked"}:
            warnings[row.subsystem] += 1
        if row.metrics is None:
            continue
        if row.metrics.power_mw is not None:
            aggregates[row.subsystem]["power"] += row.metrics.power_mw
            has_value[row.subsystem]["power"] = True
        if row.metrics.bw_total_mbs is not None:
            aggregates[row.subsystem]["bw"] += row.metrics.bw_total_mbs
            has_value[row.subsystem]["bw"] = True
        if row.metrics.hw_time_ms is not None:
            aggregates[row.subsystem]["time"] = max(aggregates[row.subsystem]["time"], row.metrics.hw_time_ms)
            has_value[row.subsystem]["time"] = True

    overview.metric_breakdown = [
        Level0MetricBreakdown(
            subsystem=subsystem,
            power_mw=aggregates[subsystem]["power"] if has_value[subsystem]["power"] else None,
            bw_total_mbs=aggregates[subsystem]["bw"] if has_value[subsystem]["bw"] else None,
            hw_time_ms=aggregates[subsystem]["time"] if has_value[subsystem]["time"] else None,
            node_count=counts[subsystem],
            warning_count=warnings[subsystem],
        )
        for subsystem in sorted(counts)
    ]


def _append_sim_node_text(data: NodeData) -> None:
    overlay = data.sim_overlay
    if overlay is None:
        return
    badges = []
    if overlay.set_clock_mhz is not None:
        badges.append(f"{overlay.set_clock_mhz:.0f}MHz")
    if overlay.power_mw is not None:
        badges.append(f"{overlay.power_mw:.1f}mW")
    for badge in badges:
        if badge not in data.summary_badges:
            data.summary_badges.append(badge)
    detail = _sim_node_detail(overlay)
    if detail and detail not in data.detail_items:
        data.detail_items.append(detail)


def _append_sim_edge_text(data: EdgeData) -> None:
    overlay = data.sim_overlay
    if overlay is None:
        return
    bits = []
    if overlay.bw_mbs is not None:
        bits.append(f"BW {overlay.bw_mbs:.1f} MB/s")
    if overlay.bw_power_mw is not None:
        bits.append(f"BW power {overlay.bw_power_mw:.1f} mW")
    if overlay.bw_mbs_worst is not None:
        bits.append(f"worst {overlay.bw_mbs_worst:.1f} MB/s")
    detail = "Sim: " + ", ".join(bits) if bits else None
    if detail and detail not in data.detail_items:
        data.detail_items.append(detail)


def _sim_node_detail(overlay: SimOverlay) -> str | None:
    bits = []
    if overlay.required_clock_mhz is not None:
        bits.append(f"req {overlay.required_clock_mhz:.1f}MHz")
    if overlay.set_clock_mhz is not None:
        bits.append(f"set {overlay.set_clock_mhz:.1f}MHz")
    if overlay.set_voltage_mv is not None:
        bits.append(f"{overlay.set_voltage_mv:.0f}mV")
    if overlay.power_mw is not None:
        bits.append(f"{overlay.power_mw:.1f}mW")
    if overlay.hw_time_ms is not None:
        bits.append(f"{overlay.hw_time_ms:.2f}ms")
    if not overlay.feasible:
        bits.append("infeasible")
    return "Sim: " + ", ".join(bits) if bits else None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_graph(db, scenario_id: str, variant_id: str | None) -> CanonicalScenarioGraph:
    if variant_id:
        return load_canonical_graph(db, scenario_id, variant_id)
    return load_base_canonical_graph(db, scenario_id)


def _level0_projection_deps() -> Level0ProjectionDeps:
    return Level0ProjectionDeps(
        sw_stack_nodes=_sw_stack_nodes,
        architecture_resource_nodes=_architecture_resource_nodes,
        buffer_nodes_from_architecture_edges=_buffer_nodes_from_architecture_edges,
        architecture_edges=_architecture_edges,
        inferred_architecture_edges=_inferred_architecture_edges,
        sw_control_edges=_sw_control_edges,
        risk_edges=_risk_edges,
        response=_response,
        pipeline_ranks=_pipeline_ranks,
        node_element=_n,
        node_label=_node_label,
        pipeline_node_type=_pipeline_node_type,
        pipeline_node_layer=_pipeline_node_layer,
        capability_badges=_capability_badges,
        operation_summary=_operation_summary,
        node_detail_items=_node_detail_items,
        stage_for_node=_stage_for_node,
        memory_descriptor=_memory_descriptor,
        memory_placement=_memory_placement,
        buffer_detail_items=_buffer_detail_items,
        safe_id=_safe_id,
        buffer_label=_buffer_label,
        topology_edges=_topology_edges,
    )


def _project_architecture(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    return _level0_project_architecture(graph, level, _level0_projection_deps())


def _project_topology(graph: CanonicalScenarioGraph, level: int) -> ViewResponse:
    return _level0_project_topology(graph, level, _level0_projection_deps())


def _reference_sizes(graph: CanonicalScenarioGraph) -> dict[str, str]:
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    sensor = anchors.get("sensor_full") or "4000x3000"
    record = overrides.get("record_out") or _resolution_to_size(design.get("resolution")) or anchors.get("record_out") or "1920x1080"
    preview = overrides.get("preview_out") or anchors.get("preview_out") or record
    fps = int(design.get("fps") or 30)
    return {
        "sensor_full": str(sensor),
        "record_out": str(record),
        "preview_out": str(preview),
        "sensor": str(sensor),
        "record": str(record),
        "preview": str(preview),
        "fps": str(fps),
        "codec": str(design.get("codec") or "H.265"),
    }


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


def _buffer_memory_from_spec(
    graph: CanonicalScenarioGraph,
    buffer_ref: str | None,
    tokens: dict[str, str],
) -> MemoryDescriptor | None:
    if not buffer_ref:
        return None
    spec = _buffer_spec(graph, buffer_ref)
    if not spec:
        return _memory_descriptor(graph, buffer_ref)
    size_ref = spec.get("size_ref")
    width, height = _parse_size(tokens.get(str(size_ref), str(size_ref)))
    return MemoryDescriptor(
        format=spec.get("format"),
        bitdepth=spec.get("bitdepth"),
        planes=spec.get("planes"),
        width=width,
        height=height,
        fps=int(tokens.get("fps", "30")),
        alignment=spec.get("alignment"),
        compression=None if spec.get("compression") == "none" else spec.get("compression"),
    )


def _buffer_placement_from_spec(graph: CanonicalScenarioGraph, buffer_ref: str | None) -> MemoryPlacement | None:
    if not buffer_ref:
        return None
    spec = _buffer_spec(graph, buffer_ref)
    if spec and spec.get("placement"):
        return MemoryPlacement(**spec["placement"])
    return _memory_placement(graph, buffer_ref)


def _buffer_spec(graph: CanonicalScenarioGraph, buffer_ref: str) -> dict[str, Any]:
    base = ((graph.scenario.pipeline or {}).get("buffers") or {}).get(buffer_ref) or {}
    override = (getattr(graph.variant, "buffer_overrides", None) or {}).get(buffer_ref) or {}
    return _deep_merge(base, override)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str | None,
    pipeline_node: dict[str, Any] | None = None,
) -> list[str]:
    if not node_id:
        return []
    config = (getattr(graph.variant, "node_configs", None) or {}).get(node_id) or {}
    details: list[str] = []
    if pipeline_node:
        role = pipeline_node.get("role")
        if role:
            details.append(f"Role: {role}")
    if not isinstance(config, dict) or not config:
        return details

    kind = config.get("kind") or config.get("type")
    if kind:
        details.append(f"Variant config: {kind}")
    mode = config.get("mode")
    if mode:
        details.append(f"Mode: {mode}")
    if kind == "sw_task" or config.get("processor") or config.get("duration_ms") is not None:
        details.append(_sw_task_summary(config))

    input_summary = _port_summary(config.get("inputs"))
    if input_summary:
        details.append("Inputs: " + input_summary)
    output_summary = _port_summary(config.get("outputs"))
    if output_summary:
        details.append("Outputs: " + output_summary)
    return details


def _task_node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node_spec: dict[str, Any],
) -> list[str]:
    details = _node_detail_items(graph, node_id, node_spec)
    if node_spec.get("buffer"):
        details.extend(_buffer_detail_items(graph, str(node_spec["buffer"])))
    return details


def _edge_detail_items(
    graph: CanonicalScenarioGraph,
    edge: dict[str, Any],
    buffer_ref: str | None,
) -> list[str]:
    details: list[str] = []
    source = edge.get("from") or edge.get("source")
    target = edge.get("to") or edge.get("target")
    if source and target:
        details.append(f"Route: {source} -> {target}")
    edge_type = edge.get("type")
    if edge_type:
        details.append(f"Edge type: {edge_type}")
    if buffer_ref:
        details.extend(_buffer_detail_items(graph, buffer_ref))
    return details


def _buffer_detail_items(graph: CanonicalScenarioGraph, buffer_ref: str | None) -> list[str]:
    if not buffer_ref:
        return []
    spec = _buffer_spec(graph, buffer_ref)
    override = (getattr(graph.variant, "buffer_overrides", None) or {}).get(buffer_ref) or {}
    details: list[str] = []
    if override:
        details.append("Buffer override: variant-specific")
    if spec:
        bits = [
            spec.get("format"),
            _size_text(spec.get("size_ref") or spec.get("size")),
            f"{spec.get('bitdepth')}b" if spec.get("bitdepth") is not None else None,
            spec.get("compression"),
            spec.get("alignment"),
        ]
        summary = " / ".join(str(bit) for bit in bits if bit)
        if summary:
            details.append(f"Buffer: {summary}")
        placement = spec.get("placement") or {}
        if placement:
            details.append("Placement: " + _placement_summary(placement))
    return details


def _sw_task_summary(config: dict[str, Any]) -> str:
    bits = [
        config.get("name") or config.get("group") or "SW task",
        config.get("processor"),
        f"{config.get('duration_ms')}ms" if config.get("duration_ms") is not None else None,
    ]
    return "SW task: " + " / ".join(str(bit) for bit in bits if bit)


def _port_summary(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        bits = [
            item.get("port"),
            _size_text(item.get("size")),
            item.get("format"),
            f"{item.get('bitwidth')}b" if item.get("bitwidth") is not None else None,
            item.get("comp"),
        ]
        items.append(" ".join(str(bit) for bit in bits if bit))
    if len(value) > 3:
        items.append(f"+{len(value) - 3} more")
    return "; ".join(items) if items else None


def _size_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value) >= 4:
        return f"{value[2]}x{value[3]}"
    if isinstance(value, dict):
        width = value.get("width")
        height = value.get("height")
        if width and height:
            return f"{width}x{height}"
    return None


def _placement_summary(placement: dict[str, Any]) -> str:
    if placement.get("llc_allocated") is True:
        mb = placement.get("llc_allocation_mb")
        policy = placement.get("llc_policy") or "llc"
        owner = placement.get("allocation_owner")
        return "LLC " + " ".join(str(part) for part in (f"{mb}MB" if mb else None, policy, owner) if part)
    return ", ".join(f"{key}={value}" for key, value in placement.items())


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


def _task_edge_removed(edge: dict[str, Any], remove_specs: list[Any]) -> bool:
    return any(isinstance(spec, dict) and _task_edge_matches(edge, spec) for spec in remove_specs)


def _task_edge_matches(edge: dict[str, Any], spec: dict[str, Any]) -> bool:
    spec_id = spec.get("id")
    if spec_id and spec_id == edge.get("id"):
        return True
    if edge.get("from") != spec.get("from") or edge.get("to") != spec.get("to"):
        return False
    for field in ("type", "buffer"):
        if spec.get(field) is not None and edge.get(field) is not None and edge.get(field) != spec.get(field):
            return False
    return True


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


def _project_drilldown(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    reference = _project_level2_reference(graph, expand)
    if reference is not None:
        return reference

    pipeline_node = _find_pipeline_node(graph, expand) or _find_pipeline_node_by_ip_ref(graph, expand)
    if pipeline_node is None:
        raise LookupError(f"Cannot expand unknown IP node: {expand}")

    node_id = pipeline_node.get("id")
    ip_ref = pipeline_node.get("ip_ref")
    ip_catalog = graph.ip_catalog.get(ip_ref or "")
    hierarchy = ip_catalog.hierarchy if ip_catalog else {}
    submodules = hierarchy.get("submodules") or []

    nodes: list[NodeElement] = [
        _n(
            f"ip-{node_id}",
            _node_label(node_id, pipeline_node),
            "ip",
            "hw",
            420,
            80,
            ip_ref=ip_ref,
            capability_badges=_capability_badges(graph, pipeline_node),
            active_operations=_operation_summary(graph, node_id, pipeline_node),
            view_hints=ViewHints(lane="hw", stage="processing", order=0, emphasis="primary"),
        )
    ]
    edges: list[EdgeElement] = []

    previous = f"ip-{node_id}"
    for idx, submodule in enumerate(submodules):
        sub_id = submodule.get("instance_id") or submodule.get("ref") or f"sub{idx}"
        current = f"sub-{_safe_id(str(sub_id))}"
        nodes.append(
            _n(
                current,
                str(sub_id),
                "submodule",
                "hw",
                250 + idx * 190,
                205,
                parent=f"ip-{node_id}",
                active_operations=_operation_summary(graph, str(sub_id), pipeline_node),
                view_hints=ViewHints(lane="hw", stage="processing", order=idx),
            )
        )
        edges.append(_e(f"e-{previous}-{current}", previous, current, "OTF"))
        previous = current

    dma_group_id = f"dma-{node_id}"
    sysmmu_id = f"sysmmu-{node_id}"
    nodes.append(
        _n(
            dma_group_id,
            f"{_node_label(node_id, pipeline_node)} DMA",
            "dma_group",
            "hw",
            420,
            350,
            parent=f"ip-{node_id}",
            dma_count=_dma_count_for_node(graph, node_id),
            view_hints=ViewHints(lane="hw", stage="processing", order=0),
        )
    )
    nodes.append(
        _n(
            sysmmu_id,
            "System MMU",
            "sysmmu",
            "hw",
            660,
            350,
            parent=f"ip-{node_id}",
            shared_resource=True,
            view_hints=ViewHints(lane="hw", stage="processing", order=1),
        )
    )
    edges.append(_e(f"e-{previous}-{dma_group_id}", previous, dma_group_id, "M2M"))
    edges.append(_e(f"e-{dma_group_id}-{sysmmu_id}", dma_group_id, sysmmu_id, "M2M"))

    for idx, edge in enumerate(_edges_touching_node(graph, node_id)):
        buffer_ref = edge.get("buffer") or f"{node_id}_PORT_{idx}"
        buffer_id = f"buf-{_safe_id(buffer_ref)}"
        nodes.append(
            _n(
                buffer_id,
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                420 + (idx * 180),
                500,
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage="processing", order=idx),
            )
        )
        edges.append(
            _e(
                f"e-{sysmmu_id}-{buffer_id}",
                sysmmu_id,
                buffer_id,
                _edge_flow_type(edge),
                buffer_ref=buffer_ref,
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_edge_detail_items(graph, edge, buffer_ref),
            )
        )

    return _response(
        graph=graph,
        level=2,
        mode=f"drilldown:{node_id}",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": 980, "canvas_h": 650, "layout": "ip-drilldown", "expand": node_id},
    )


def _response(
    graph: CanonicalScenarioGraph,
    level: int,
    mode: str,
    nodes: list[NodeElement],
    edges: list[EdgeElement],
    metadata: dict[str, Any],
) -> ViewResponse:
    enriched_metadata = dict(metadata)
    enriched_metadata["variant_overlay"] = _variant_overlay_metadata(graph)
    return ViewResponse(
        level=level,
        mode=mode,
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        nodes=nodes,
        edges=edges,
        risks=_risk_cards(graph),
        summary=_summary(graph),
        metadata=enriched_metadata,
        overlays_available=["issues", "review-gate", "memory-path", "llc-allocation", "compression"],
        level0_resource_overview=build_resource_overview(graph) if level == 0 else None,
    )


def _variant_overlay_metadata(graph: CanonicalScenarioGraph) -> dict[str, Any]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    topology_patch = getattr(graph.variant, "topology_patch", None) or {}
    node_configs = getattr(graph.variant, "node_configs", None) or {}
    buffer_overrides = getattr(graph.variant, "buffer_overrides", None) or {}
    return {
        "resolved": bool(getattr(graph.variant, "resolved", True)),
        "inheritance_chain": list(getattr(graph.variant, "inheritance_chain", None) or []),
        "disabled_nodes": list(routing.get("disabled_nodes") or []),
        "disabled_edge_count": len(routing.get("disabled_edges") or []),
        "topology_patch": {
            "add_nodes": len(topology_patch.get("add_nodes") or []),
            "add_edges": len(topology_patch.get("add_edges") or []),
            "remove_edges": len(topology_patch.get("remove_edges") or []),
        },
        "node_config_count": len(node_configs),
        "buffer_override_count": len(buffer_overrides),
        "sw_task_count": sum(
            1
            for config in node_configs.values()
            if isinstance(config, dict)
            and (config.get("kind") == "sw_task" or config.get("processor"))
        ),
    }


def _summary(graph: CanonicalScenarioGraph) -> ViewSummary:
    metadata = graph.scenario.metadata_ or {}
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    size_overrides = getattr(graph.variant, "size_overrides", None) or {}
    fps = int(design.get("fps") or 30)
    period_ms = round(1000 / fps, 2) if fps else 0.0
    resolution = (
        size_overrides.get("record_out")
        or _resolution_to_size(design.get("resolution"))
        or anchors.get("record_out")
        or str(design.get("resolution", "unknown"))
    )
    subtitle = f"{design.get('resolution', resolution)} {fps}fps"
    if design.get("codec"):
        subtitle = f"{subtitle}, {design['codec']}"
    return ViewSummary(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        name=metadata.get("name") or graph.scenario_id,
        subtitle=subtitle,
        period_ms=period_ms,
        budget_ms=round(period_ms * 0.9, 2) if period_ms else 0.0,
        resolution=str(resolution).replace("x", " x "),
        fps=fps,
        variant_label=graph.soc.id if graph.soc else graph.scenario.project_ref,
        notes=_latest_evidence_note(graph),
        captured_at=_latest_evidence_timestamp(graph),
    )


def _sw_stack_nodes(graph: CanonicalScenarioGraph) -> list[NodeElement]:
    """Build scenario-specific SW overview nodes.

    This is intentionally not a full Android stack model.  It shows only the
    stack families implied by scenario metadata and active HW resources so
    non-camera scenarios do not inherit Camera HAL/V4L2 by default.
    """
    categories = {str(value).lower() for value in (graph.scenario.metadata_ or {}).get("category", [])}
    domains = {str(value).lower() for value in (graph.scenario.metadata_ or {}).get("domain", [])}
    resource_kinds = {_architecture_resource_kind(graph, node) for node in graph.pipeline_nodes}
    tags = categories | domains | resource_kinds
    if _camera_overview_uses_display(graph):
        tags.add("camera")
    specs: list[tuple[str, str, str, str, str, int]] = []

    def add(node_id: str, label: str, layer: str, stage: str, order: int) -> None:
        spec = (node_id, label, "sw", layer, stage, order)
        if spec not in specs:
            specs.append(spec)

    if "camera" in tags or "sensor" in tags or "isp" in tags:
        add("sw-camera-app", "Camera App", "app", "capture", 0)
        add("sw-camera-fw", "CameraService", "framework", "capture", 0)
        add("sw-camera-hal", "Camera HAL", "hal", "capture", 0)
        add("sw-camera-driver", "V4L2 Camera Driver", "kernel", "capture", 0)

    if "audio" in tags:
        add("sw-audio-app", "Audio App", "app", "capture", 0)
        add("sw-audio-fw", "AudioFlinger", "framework", "processing", 0)
        add("sw-audio-hal", "Audio HAL", "hal", "processing", 0)
        add("sw-audio-driver", "ALSA / PCM Driver", "kernel", "processing", 0)

    if "video" in tags or "video_playback" in tags or "mfc" in tags or "codec" in tags:
        label = "Camera App" if "camera" in tags else "Player App"
        framework = "MediaRecorder" if "camera" in tags else "MediaExtractor"
        if "camera" not in tags:
            add("sw-media-app", label, "app", "processing", 1)
        add("sw-media-fw", framework, "framework", "processing", 1)
        add("sw-codec-hal", "Codec2 HAL", "hal", "encode", 0)
        add("sw-codec-driver", "MFC Driver", "kernel", "encode", 0)

    if "camera" in tags or "display" in tags or "dpu" in tags or "panel" in tags:
        add("sw-surface", "SurfaceFlinger", "framework", "display", 0)
        add("sw-hwc", "HWC / Display HAL", "hal", "display", 0)
        add("sw-drm", "DRM / KMS", "kernel", "display", 0)

    if "game" in tags or "gpu" in tags:
        add("sw-game-app", "Game App", "app", "processing", 0)
        add("sw-graphics-fw", "Graphics Framework", "framework", "processing", 2)
        add("sw-gpu-hal", "GPU HAL", "hal", "processing", 1)
        add("sw-gpu-driver", "GPU Driver", "kernel", "processing", 1)

    return [
        _n(
            node_id,
            label,
            node_type,
            layer,
            STAGE_X.get(stage, STAGE_X["processing"]),
            LANE_Y[layer],
            detail_items=[f"Scenario SW stack: {label}"],
            view_hints=ViewHints(lane=layer, stage=stage, order=order),
        )
        for node_id, label, node_type, layer, stage, order in specs
    ]


def _architecture_resource_nodes(
    graph: CanonicalScenarioGraph,
    stage_orders: dict[tuple[str, str], int],
) -> tuple[list[NodeElement], dict[str, str]]:
    groups: dict[str, dict[str, Any]] = {}
    node_map: dict[str, str] = {}
    disabled_nodes = _disabled_node_ids(graph)

    for pipeline_node in graph.pipeline_nodes:
        node_id = pipeline_node.get("id")
        if not node_id:
            continue
        if str(node_id) in disabled_nodes:
            continue
        if _is_explicit_sw_task(graph, pipeline_node):
            layer = _sw_layer_for_node(pipeline_node)
            stage = _stage_for_node(node_id, pipeline_node)
            order = _next_order(stage_orders, layer, stage)
            view_id = f"sw-task-{_safe_id(node_id)}"
            groups[view_id] = {
                "id": view_id,
                "label": _node_label(node_id, pipeline_node),
                "layer": layer,
                "type": "sw",
                "stage": stage,
                "order": order,
                "members": [pipeline_node],
                "detail_items": _node_detail_items(graph, node_id, pipeline_node),
            }
            node_map[str(node_id)] = view_id
            continue

        kind = _architecture_resource_kind(graph, pipeline_node)
        view_id = f"res-{kind}"
        node_map[str(node_id)] = view_id
        group_layer = "external" if kind in {"sensor", "panel"} else ("memory" if kind == "memory" else "hw")
        group = groups.setdefault(
            view_id,
            {
                "id": view_id,
                "label": _architecture_resource_label(kind),
                "layer": group_layer,
                "type": "ip" if kind not in {"memory"} else "buffer",
                "stage": _architecture_resource_stage(kind, node_id, pipeline_node),
                "members": [],
                "capability_badges": [],
                "detail_items": [],
            },
        )
        group["members"].append(pipeline_node)
        for badge in _capability_badges(graph, pipeline_node):
            if badge not in group["capability_badges"]:
                group["capability_badges"].append(badge)

    if _camera_overview_uses_display(graph):
        _ensure_inferred_resource_group(groups, "sensor", "external")
        _ensure_inferred_resource_group(groups, "dpu", "hw")
        _ensure_inferred_resource_group(groups, "panel", "external")

    nodes: list[NodeElement] = []
    for group in groups.values():
        members = group["members"]
        layer = group["layer"]
        stage = group["stage"]
        order = group.get("order")
        if order is None:
            order = _next_order(stage_orders, layer, stage)
        detail_items = list(group.get("detail_items") or [])
        if members:
            detail_items.append(
                "Members: "
                + ", ".join(str(member.get("id")) for member in members[:8])
                + (f" +{len(members) - 8}" if len(members) > 8 else "")
            )
        representative = members[0] if members else {}
        nodes.append(
            _n(
                group["id"],
                group["label"],
                group["type"],
                layer,
                STAGE_X.get(stage, STAGE_X["processing"]) + (int(order) * 115),
                LANE_Y[layer],
                ip_ref=representative.get("ip_ref"),
                summary_badges=[f"{len(members)} nodes"] if len(members) > 1 else [],
                capability_badges=list(group.get("capability_badges") or [])[:6],
                active_operations=_operation_summary(graph, representative.get("id"), representative) if representative else None,
                detail_items=detail_items,
                collapsed_children_count=max(0, len(members) - 1),
                view_hints=ViewHints(lane=layer, stage=stage, order=int(order)),
            )
        )
    return nodes, node_map


def _ensure_inferred_resource_group(groups: dict[str, dict[str, Any]], kind: str, layer: str) -> None:
    view_id = f"res-{kind}"
    if view_id in groups:
        return
    groups[view_id] = {
        "id": view_id,
        "label": _architecture_resource_label(kind),
        "layer": layer,
        "type": "ip",
        "stage": _architecture_resource_stage(kind, None, {}),
        "members": [],
        "capability_badges": ["inferred"],
        "detail_items": ["Inferred camera display path for Level 0 overview."],
    }


def _architecture_edges(graph: CanonicalScenarioGraph, node_map: dict[str, str]) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    remove_specs = _disabled_edge_specs(graph)
    for idx, edge in enumerate(graph.pipeline_edges):
        if _task_edge_removed(edge, remove_specs):
            continue
        source = node_map.get(str(edge.get("from")))
        target = node_map.get(str(edge.get("to")))
        if not source or not target or source == target:
            continue
        flow_type = _edge_flow_type(edge)
        buffer_ref = edge.get("buffer")
        if buffer_ref:
            # Level 0 must still show the direct HW pipeline relationship.
            # The buffer edges provide memory detail; this summary edge keeps
            # HW-to-HW connectivity visible in the architecture overview.
            edges.append(
                _e(
                    f"e-{idx}-hw-summary",
                    source,
                    target,
                    flow_type,
                    buffer_ref=buffer_ref,
                    label=f"{flow_type} path",
                    detail_items=_edge_detail_items(graph, edge, buffer_ref),
                )
            )
            buffer_id = _architecture_buffer_id(buffer_ref)
            edges.append(_e(f"e-{idx}-src-buf", source, buffer_id, flow_type, buffer_ref=buffer_ref, detail_items=_edge_detail_items(graph, edge, buffer_ref)))
            edges.append(_e(f"e-{idx}-buf-tgt", buffer_id, target, flow_type, buffer_ref=buffer_ref, detail_items=_edge_detail_items(graph, edge, buffer_ref)))
        else:
            edges.append(_e(f"e-{idx}-{source}-{target}", source, target, flow_type, detail_items=_edge_detail_items(graph, edge, None)))
    return edges


def _inferred_architecture_edges(graph: CanonicalScenarioGraph, node_ids: set[str]) -> list[EdgeElement]:
    if not _camera_overview_uses_display(graph):
        return []

    edges: list[EdgeElement] = []
    if "res-sensor" in node_ids:
        target = next((node_id for node_id in ("res-camera_frontend", "res-isp") if node_id in node_ids), None)
        has_declared_sensor_path = any(
            _architecture_resource_kind(graph, source_node) == "sensor"
            for edge in graph.pipeline_edges
            if (source_node := _find_pipeline_node(graph, edge.get("from")))
        )
        if target and not has_declared_sensor_path:
            edges.append(
                _e(
                    "e-inferred-sensor-input",
                    "res-sensor",
                    target,
                    "OTF",
                    label="sensor in",
                    detail_items=["Inferred camera sensor input for Level 0 overview."],
                )
            )

    if "res-dpu" not in node_ids:
        return edges

    has_declared_dpu_path = any(
        _architecture_resource_kind(graph, target_node) == "dpu"
        for edge in graph.pipeline_edges
        if (target_node := _find_pipeline_node(graph, edge.get("to")))
    )
    if not has_declared_dpu_path:
        source = next((node_id for node_id in ("res-isp", "res-camera_frontend", "res-mfc") if node_id in node_ids), None)
        if source:
            edges.append(
                _e(
                    "e-inferred-camera-display",
                    source,
                    "res-dpu",
                    "M2M",
                    label="display path",
                    detail_items=["Inferred camera preview/display path for Level 0 overview."],
                )
            )

    has_declared_panel_path = any(
        _architecture_resource_kind(graph, source_node) == "dpu" and _architecture_resource_kind(graph, target_node) == "panel"
        for edge in graph.pipeline_edges
        if (source_node := _find_pipeline_node(graph, edge.get("from"))) and (target_node := _find_pipeline_node(graph, edge.get("to")))
    )
    if "res-panel" in node_ids and not has_declared_panel_path:
        edges.append(
            _e(
                "e-inferred-dpu-panel",
                "res-dpu",
                "res-panel",
                "OTF",
                label="display out",
                detail_items=["Inferred panel output for Level 0 overview."],
            )
        )
    return edges


def _topology_edges(graph: CanonicalScenarioGraph) -> list[EdgeElement]:
    edges: list[EdgeElement] = []
    for idx, edge in enumerate(graph.pipeline_edges):
        source = f"ip-{edge.get('from')}"
        target = f"ip-{edge.get('to')}"
        flow_type = _edge_flow_type(edge)
        buffer_ref = edge.get("buffer")
        if buffer_ref:
            buffer_id = f"buf-{_safe_id(buffer_ref)}"
            details = _edge_detail_items(graph, edge, buffer_ref)
            edges.append(_e(f"e-topo-{idx}-src-buf", source, buffer_id, flow_type, buffer_ref=buffer_ref, detail_items=details))
            edges.append(_e(f"e-topo-{idx}-buf-tgt", buffer_id, target, flow_type, buffer_ref=buffer_ref, detail_items=details))
        else:
            edges.append(_e(f"e-topo-{idx}", source, target, flow_type, detail_items=_edge_detail_items(graph, edge, None)))
    return edges


def _buffer_nodes_from_architecture_edges(
    graph: CanonicalScenarioGraph,
    node_map: dict[str, str],
    stage_orders: dict[tuple[str, str], int],
) -> list[NodeElement]:
    nodes: list[NodeElement] = []
    seen: set[str] = set()
    for edge in graph.pipeline_edges:
        buffer_ref = edge.get("buffer")
        if not buffer_ref or buffer_ref in seen:
            continue
        source = node_map.get(str(edge.get("from")))
        target = node_map.get(str(edge.get("to")))
        if not source or not target or source == target:
            continue
        seen.add(buffer_ref)
        target_node = _find_pipeline_node(graph, edge.get("to"))
        source_node = _find_pipeline_node(graph, edge.get("from"))
        stage = _stage_for_node(edge.get("to"), target_node or source_node or {})
        order = _next_order(stage_orders, "memory", stage)
        nodes.append(
            _n(
                _architecture_buffer_id(buffer_ref),
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                STAGE_X.get(stage, STAGE_X["processing"]) + (order * 170),
                LANE_Y["memory"],
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage=stage, order=order),
            )
        )
    return nodes


def _buffer_nodes_from_edges(
    graph: CanonicalScenarioGraph,
    stage_orders: dict[tuple[str, str], int],
) -> list[NodeElement]:
    nodes: list[NodeElement] = []
    seen: set[str] = set()
    for edge in graph.pipeline_edges:
        buffer_ref = edge.get("buffer")
        if not buffer_ref or buffer_ref in seen:
            continue
        seen.add(buffer_ref)
        source_node = _find_pipeline_node(graph, edge.get("from"))
        target_node = _find_pipeline_node(graph, edge.get("to"))
        stage = _stage_for_node(edge.get("to"), target_node or source_node or {})
        order = _next_order(stage_orders, "memory", stage)
        nodes.append(
            _n(
                f"buf-{_safe_id(buffer_ref)}",
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                STAGE_X.get(stage, STAGE_X["processing"]) + (order * 170),
                LANE_Y["memory"],
                memory=_memory_descriptor(graph, buffer_ref),
                placement=_memory_placement(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage=stage, order=order),
            )
        )
    return nodes


def _sw_control_edges(
    graph: CanonicalScenarioGraph,
    node_map: dict[str, str],
    node_ids: set[str],
) -> list[EdgeElement]:
    edges: list[EdgeElement] = []

    def add(edge_id: str, source: str, target: str, label: str | None = None) -> None:
        if source in node_ids and target in node_ids:
            edges.append(_e(edge_id, source, target, "control", label=label))

    add("e-sw-camera-0", "sw-camera-app", "sw-camera-fw", "Camera API")
    add("e-sw-camera-1", "sw-camera-fw", "sw-camera-hal", "HAL call")
    add("e-sw-camera-2", "sw-camera-hal", "sw-camera-driver", "V4L2")
    if "res-sensor" in node_ids:
        add("e-sw-camera-sensor", "sw-camera-driver", "res-sensor", "subdev")
    elif "res-isp" in node_ids:
        add("e-sw-camera-isp", "sw-camera-driver", "res-isp", "subdev")

    add("e-sw-audio-0", "sw-audio-app", "sw-audio-fw", "AudioTrack")
    add("e-sw-audio-1", "sw-audio-fw", "sw-audio-hal", "Audio HAL")
    add("e-sw-audio-2", "sw-audio-hal", "sw-audio-driver", "PCM")

    media_app_source = "sw-camera-app" if "sw-camera-app" in node_ids else "sw-media-app"
    add("e-sw-media-0", media_app_source, "sw-media-fw", "Media API")
    add("e-sw-media-1", "sw-media-fw", "sw-codec-hal", "Codec2")
    add("e-sw-media-2", "sw-codec-hal", "sw-codec-driver", "V4L2 M2M")
    add("e-sw-media-mfc", "sw-codec-driver", "res-mfc", "driver")
    add("e-sw-media-apv", "sw-codec-driver", "res-apv", "driver")

    add("e-sw-display-0", "sw-surface", "sw-hwc", "composition")
    add("e-sw-display-1", "sw-hwc", "sw-drm", "KMS")
    add("e-sw-display-dpu", "sw-drm", "res-dpu", "atomic")

    add("e-sw-game-0", "sw-game-app", "sw-graphics-fw", "render")
    add("e-sw-game-1", "sw-graphics-fw", "sw-gpu-hal", "EGL/Vulkan")
    add("e-sw-game-2", "sw-gpu-hal", "sw-gpu-driver", "ioctl")
    add("e-sw-game-gpu", "sw-gpu-driver", "res-gpu", "driver")

    for pipeline_node in graph.pipeline_nodes:
        node_id = pipeline_node.get("id")
        if not node_id:
            continue
        view_id = node_map.get(str(node_id))
        if not view_id or view_id not in node_ids:
            continue
        role = str(pipeline_node.get("role") or "").lower()
        if role in {"sw_task", "eis", "m2m_scaler", "audio_decode", "demux", "dsp_offload"}:
            add(f"e-sw-task-{_safe_id(node_id)}", "sw-camera-driver" if "sw-camera-driver" in node_ids else "sw-media-fw", view_id, "SW task")

    return edges


def _risk_edges(graph: CanonicalScenarioGraph, node_map: dict[str, str] | None = None) -> list[EdgeElement]:
    gate = run_review_gate(graph)
    matched_issue_ids = {matched.issue_id for matched in gate.matched_issues}
    affected_ip_refs: set[str] = set()
    for issue in graph.issues:
        if issue.id not in matched_issue_ids:
            continue
        for affected in issue.affects_ip or []:
            ip_ref = affected.get("ip_ref")
            if ip_ref:
                affected_ip_refs.add(ip_ref)

    edges: list[EdgeElement] = []
    for pipeline_node in graph.pipeline_nodes:
        if pipeline_node.get("ip_ref") not in affected_ip_refs:
            continue
        node_id = pipeline_node.get("id")
        view_id = (node_map or {}).get(str(node_id)) or f"ip-{node_id}"
        edges.append(_e(f"e-risk-{node_id}", view_id, view_id, "risk", label="Known issue"))
    return edges


def _risk_cards(graph: CanonicalScenarioGraph) -> list[RiskCard]:
    gate = run_review_gate(graph)
    cards: list[RiskCard] = []
    for idx, issue in enumerate(gate.matched_issues, start=1):
        cards.append(
            RiskCard(
                id=f"R{idx}",
                title=issue.title,
                component=", ".join(_issue_components(graph, issue.issue_id)) or issue.issue_id,
                description=f"Matched by {issue.matched_by}. Status: {issue.status or 'unknown'}",
                severity=_severity_to_card(issue.severity),
                impact="Known Issue",
            )
        )
    for rule in gate.matched_rules:
        if rule.status == "PASS":
            continue
        cards.append(
            RiskCard(
                id=f"R{len(cards) + 1}",
                title=f"{rule.status}: {rule.rule_id}",
                component="Review Gate",
                description=rule.message or rule.rule_id,
                severity="High" if rule.status == "BLOCK" else "Medium",
                impact="Gate Result",
            )
        )
    return cards


def _issue_components(graph: CanonicalScenarioGraph, issue_id: str) -> list[str]:
    for issue in graph.issues:
        if issue.id == issue_id:
            return [item.get("submodule") or item.get("ip_ref") for item in issue.affects_ip or [] if item]
    return []


def _architecture_resource_kind(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> str:
    text = (
        f"{pipeline_node.get('id', '')} {pipeline_node.get('ip_ref', '')} "
        f"{pipeline_node.get('role', '')} {pipeline_node.get('node_type', '')}"
    ).lower()
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower()
    if "sensor" in text or category == "sensor":
        return "sensor"
    if "panel" in text or "display_output" in text:
        return "panel"
    if any(token in text for token in ("dpu", "decon", "display_controller")) or category == "display":
        return "dpu"
    if any(token in text for token in ("csis", "csi", "pdp")):
        return "camera_frontend"
    if any(token in text for token in ("isp", "3aa", "byrp", "rgbp", "yuv", "mcsc", "mtnr", "msnr", "lme", "gdc")) or category == "camera":
        return "isp"
    if "apv" in text:
        return "apv"
    if "jpeg" in text:
        return "jpeg"
    if any(token in text for token in ("mfc", "codec", "enc", "dec")) or category == "codec":
        return "mfc"
    if "gpu" in text or category == "gpu":
        return "gpu"
    if "npu" in text or category == "npu":
        return "npu"
    if category == "memory":
        return "memory"
    if category:
        return category
    return _safe_id(str(pipeline_node.get("id") or "hw"))


def _architecture_resource_label(kind: str) -> str:
    labels = {
        "sensor": "Sensor Module",
        "camera_frontend": "Camera Frontend",
        "isp": "ISP",
        "mfc": "MFC",
        "apv": "APV",
        "jpeg": "JPEG",
        "dpu": "DPU",
        "panel": "Display Module",
        "gpu": "GPU",
        "npu": "NPU",
        "memory": "Memory Resource",
        "cpu": "CPU / SW Resource",
    }
    return labels.get(kind, kind.replace("_", " ").title())


def _architecture_resource_stage(kind: str, node_id: str | None, pipeline_node: dict[str, Any]) -> str:
    if kind in {"sensor", "camera_frontend"}:
        return "capture"
    if kind in {"mfc", "apv", "jpeg"}:
        return "encode"
    if kind in {"dpu", "panel", "gpu"}:
        return "display"
    return _stage_for_node(node_id, pipeline_node)


def _architecture_buffer_id(buffer_ref: str) -> str:
    return f"buf-arch-{_safe_id(buffer_ref)}"


def _disabled_node_ids(graph: CanonicalScenarioGraph) -> set[str]:
    return set(((getattr(graph.variant, "routing_switch", None) or {}).get("disabled_nodes") or []))


def _disabled_edge_specs(graph: CanonicalScenarioGraph) -> list[Any]:
    routing = getattr(graph.variant, "routing_switch", None) or {}
    patch = getattr(graph.variant, "topology_patch", None) or {}
    return [
        *(routing.get("disabled_edges") or []),
        *(patch.get("remove_edges") or []),
    ]


def _camera_overview_uses_display(graph: CanonicalScenarioGraph) -> bool:
    disabled_nodes = _disabled_node_ids(graph)
    if disabled_nodes:
        declared_nodes = (getattr(graph.scenario, "pipeline", {}) or {}).get("nodes") or []
        for node in declared_nodes:
            if node.get("id") in disabled_nodes and _architecture_resource_kind(graph, node) in {"dpu", "panel"}:
                return False

    metadata = graph.scenario.metadata_ or {}
    tags = {str(value).lower() for value in metadata.get("category", [])}
    tags.update(str(value).lower() for value in metadata.get("domain", []))
    tags.add(str(getattr(graph.scenario, "id", "") or "").lower())
    tags.add(str(metadata.get("name", "") or "").lower())
    return any("camera" in tag for tag in tags)


def _is_explicit_sw_task(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> bool:
    role = str(pipeline_node.get("role") or "").lower()
    node_type = str(pipeline_node.get("node_type") or pipeline_node.get("kind") or "").lower()
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower()
    if node_type in {"sw", "task", "cpu"}:
        return True
    if category != "cpu":
        return False
    return role in {
        "source",
        "sw_task",
        "eis",
        "m2m_scaler",
        "audio_decode",
        "dsp_offload",
        "audio_hal",
        "audio_output",
        "bt_output",
        "demux",
    }


def _sw_layer_for_node(pipeline_node: dict[str, Any]) -> str:
    text = f"{pipeline_node.get('id', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("app", "source", "network", "storage")):
        return "app"
    if any(token in text for token in ("hal", "audio_hal")):
        return "hal"
    if any(token in text for token in ("driver", "v4l2", "drm", "kms", "dsp", "offload", "eis", "m2m_scaler")):
        return "kernel"
    return "framework"


def _capability_badges(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> list[str]:
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    if not ip_row:
        return []
    supported = (ip_row.capabilities or {}).get("supported_features") or {}
    badges: list[str] = []
    if supported.get("hdr_formats"):
        badges.extend(str(v) for v in supported["hdr_formats"][:2])
    if supported.get("compression"):
        badges.extend(str(v) for v in supported["compression"][:1])
    if supported.get("bitdepth"):
        badges.append(f"{max(supported['bitdepth'])}b")
    ops = _operation_summary(graph, pipeline_node.get("id", ""), pipeline_node)
    if ops and ops.crop:
        badges.append("CROP")
    if ops and ops.scale:
        badges.append("SCALE")
    if ops and ops.rotate is not None:
        badges.append("ROTATE")
    return badges[:5]


def _operation_summary(
    graph: CanonicalScenarioGraph,
    node_id: str,
    pipeline_node: dict[str, Any],
) -> OperationSummary | None:
    lowered = f"{node_id} {pipeline_node.get('ip_ref', '')}".lower()
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    input_size = anchors.get("sensor_full")
    output_size = overrides.get("record_out") or anchors.get("record_out")

    if any(token in lowered for token in ("isp", "mcsc", "mlsc", "tnr", "dns")):
        return OperationSummary(
            crop=bool(design.get("zoom") or "isp" in lowered),
            scale=bool(input_size and output_size and input_size != output_size),
            scale_from=input_size,
            scale_to=output_size,
            colorspace_convert="RAW->YUV" if "isp" in lowered else None,
        )
    if any(token in lowered for token in ("gdc", "rot", "dpu")):
        return OperationSummary(rotate=0 if "dpu" in lowered else 90, compose="dpu" in lowered)
    return None


def _memory_descriptor(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryDescriptor:
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    size = overrides.get("record_out") or anchors.get("record_out")
    width, height = _parse_size(size)
    codec = design.get("codec")
    is_bitstream = "bitstream" in buffer_ref.lower() or "enc" in buffer_ref.lower()
    return MemoryDescriptor(
        format=str(codec) if is_bitstream and codec else _format_for_buffer(buffer_ref),
        bitdepth=10 if design.get("hdr") not in (None, "SDR") else 8,
        planes=1 if is_bitstream or "raw" in buffer_ref.lower() else 2,
        width=width,
        height=height,
        fps=int(design.get("fps") or 30),
        alignment="64B",
        compression=_compression_for_buffer(graph),
    )


def _memory_placement(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryPlacement:
    allocations = (graph.variant.ip_requirements or {}).get("llc", {}).get("required_allocations") or {}
    owner = None
    allocation_mb = None
    for key, value in allocations.items():
        owner = str(key)
        allocation_mb = _parse_mb(value)
        if str(key).lower() in buffer_ref.lower() or str(key).lower() in {"mfc", "isp.tnr"}:
            break
    return MemoryPlacement(
        llc_allocated=bool(allocations),
        llc_allocation_mb=allocation_mb,
        llc_policy="dedicated" if allocations else "none",
        allocation_owner=owner,
        expected_bw_reduction_gbps=2.0 if allocations else None,
    )


def _pipeline_ranks(graph: CanonicalScenarioGraph) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for idx, node in enumerate(graph.pipeline_nodes):
        node_id = node.get("id")
        if node_id:
            ranks[node_id] = idx
    changed = True
    while changed:
        changed = False
        for edge in graph.pipeline_edges:
            source = edge.get("from")
            target = edge.get("to")
            if source in ranks and target in ranks and ranks[target] <= ranks[source]:
                ranks[target] = ranks[source] + 1
                changed = True
    return ranks


def _stage_for_node(node_id: str | None, pipeline_node: dict[str, Any]) -> str:
    text = f"{node_id or ''} {pipeline_node.get('ip_ref', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("sensor", "csis", "pdp", "csi")):
        return "capture"
    if any(token in text for token in ("mfc", "codec", "enc")):
        return "encode"
    if any(token in text for token in ("dpu", "display", "drm")):
        return "display"
    return "processing"


def _edge_flow_type(edge: dict[str, Any]) -> str:
    flow_type = str(edge.get("type") or "M2M")
    if flow_type in {"OTF", "vOTF", "M2M", "control", "risk"}:
        return flow_type
    lowered = flow_type.lower()
    if lowered == "votf":
        return "vOTF"
    if lowered == "otf":
        return "OTF"
    if lowered == "m2m":
        return "M2M"
    return "M2M"


def _find_pipeline_node(graph: CanonicalScenarioGraph, node_id: str | None) -> dict[str, Any] | None:
    for node in graph.pipeline_nodes:
        if node.get("id") == node_id:
            return node
    return None


def _find_pipeline_node_by_ip_ref(graph: CanonicalScenarioGraph, ip_ref: str | None) -> dict[str, Any] | None:
    for node in graph.pipeline_nodes:
        if node.get("ip_ref") == ip_ref:
            return node
    return None


def _edges_touching_node(graph: CanonicalScenarioGraph, node_id: str | None) -> list[dict[str, Any]]:
    return [edge for edge in graph.pipeline_edges if edge.get("from") == node_id or edge.get("to") == node_id]


def _first_hw_node(graph: CanonicalScenarioGraph, tokens: tuple[str, ...]) -> str | None:
    for node in graph.pipeline_nodes:
        text = f"{node.get('id', '')} {node.get('ip_ref', '')}".lower()
        if any(token in text for token in tokens):
            return node.get("id")
    return None


def _is_memory_ip(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> bool:
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    return bool(ip_row and ip_row.category == "memory")


def _pipeline_node_layer(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> str:
    explicit = str(pipeline_node.get("layer") or "").lower()
    if explicit in {"app", "framework", "hal", "kernel", "hw", "memory"}:
        return explicit
    node_type = str(pipeline_node.get("node_type") or pipeline_node.get("kind") or "").lower()
    if node_type in {"sw", "task", "cpu"}:
        return _sw_layer_for_node(pipeline_node)
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    if str(getattr(ip_row, "category", "") or "").lower() == "cpu":
        return _sw_layer_for_node(pipeline_node)
    if _is_memory_ip(graph, pipeline_node):
        return "memory"
    return "hw"


def _pipeline_node_type(layer: str) -> str:
    if layer in {"app", "framework", "hal", "kernel"}:
        return "sw"
    if layer == "memory":
        return "buffer"
    return "ip"


def _node_label(node_id: str, pipeline_node: dict[str, Any]) -> str:
    label = pipeline_node.get("label") or node_id
    return str(label).replace("_", " ").upper()


def _buffer_label(buffer_ref: str) -> str:
    return str(buffer_ref).replace("_", " ").title()


def _safe_id(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in str(value)).strip("-")


def _next_order(stage_orders: dict[tuple[str, str], int], layer: str, stage: str) -> int:
    key = (layer, stage)
    order = stage_orders.get(key, 0)
    stage_orders[key] = order + 1
    return order


def _parse_size(size: Any) -> tuple[int | None, int | None]:
    if not isinstance(size, str) or "x" not in size:
        return None, None
    left, right = size.lower().split("x", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def _resolution_to_size(resolution: Any) -> str | None:
    mapping = {
        "FHD": "1920x1080",
        "UHD": "3840x2160",
        "4K": "3840x2160",
        "8K": "7680x4320",
    }
    return mapping.get(str(resolution).upper())


def _parse_mb(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    try:
        if text.endswith("mb"):
            return float(text[:-2])
        return float(text)
    except ValueError:
        return None


def _format_for_buffer(buffer_ref: str) -> str:
    lowered = buffer_ref.lower()
    if "raw" in lowered:
        return "RAW10"
    if "preview" in lowered:
        return "NV12"
    if "record" in lowered:
        return "NV12"
    return "YUV"


def _compression_for_buffer(graph: CanonicalScenarioGraph) -> str | None:
    for ip_row in graph.ip_catalog.values():
        compression = ((ip_row.capabilities or {}).get("supported_features") or {}).get("compression")
        if compression:
            return compression[0]
    return None


def _dma_count_for_node(graph: CanonicalScenarioGraph, node_id: str | None) -> int:
    memory_edges = [edge for edge in _edges_touching_node(graph, node_id) if edge.get("type") == "M2M"]
    return max(1, len(memory_edges))


def _latest_evidence_note(graph: CanonicalScenarioGraph) -> str | None:
    if not graph.evidence:
        return None
    evidence = graph.evidence[-1]
    run = getattr(evidence, "run", None) or {}
    tool = run.get("tool")
    source = run.get("source")
    if tool and source:
        return f"Evidence from {tool} ({source})."
    return "Evidence is available for this variant."


def _latest_evidence_timestamp(graph: CanonicalScenarioGraph) -> str | None:
    if not graph.evidence:
        return None
    run = getattr(graph.evidence[-1], "run", None) or {}
    return run.get("timestamp")


def _severity_to_card(severity: str | None) -> str:
    mapping = {
        "critical": "Critical",
        "heavy": "High",
        "medium": "Medium",
        "low": "Low",
    }
    return mapping.get(str(severity).lower(), "Medium")
