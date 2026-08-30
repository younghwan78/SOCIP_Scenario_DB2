"""View API — Pydantic models for the pipeline viewer response."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ViewHints(BaseModel):
    lane: str | None = None
    stage: str | None = None
    order: int = 0
    width: int | None = None
    height: int | None = None
    emphasis: Literal["normal", "primary", "muted", "risk"] = "normal"
    collapsed: bool = False


class OperationSummary(BaseModel):
    crop: bool = False
    crop_ratio: float | None = None
    crop_region: dict | None = None
    scale: bool = False
    scale_from: str | None = None
    scale_to: str | None = None
    scale_ratio: float | None = None
    rotate: int | None = None
    compose: bool = False
    colorspace_convert: str | None = None


class MemoryDescriptor(BaseModel):
    format: str | None = None
    bitdepth: int | None = None
    planes: int | None = None
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    stride_bytes: int | None = None
    size_bytes: int | None = None
    alignment: str | None = None
    compression: str | None = None


class MemoryPlacement(BaseModel):
    """LLC allocation is separate from compression — do not conflate."""
    llc_allocated: bool = False
    llc_allocation_mb: float | None = None
    llc_policy: Literal["none", "shared", "dedicated", "pinned"] = "none"
    allocation_owner: str | None = None
    expected_bw_reduction_gbps: float | None = None


class SimOverlay(BaseModel):
    required_clock_mhz: float | None = None
    set_clock_mhz: float | None = None
    set_voltage_mv: float | None = None
    power_mw: float | None = None
    hw_time_ms: float | None = None
    feasible: bool = True
    evidence_id: str | None = None
    # Frame-0 schedule window from evidence timeline_events; critical marks
    # membership of the simulated critical path, bottleneck the OTF-group limiter.
    start_ms: float | None = None
    end_ms: float | None = None
    critical: bool = False
    bottleneck: bool = False


class EdgeSimOverlay(BaseModel):
    bw_mbs: float | None = None
    bw_power_mw: float | None = None
    bw_mbs_worst: float | None = None
    evidence_id: str | None = None


class IoSummary(BaseModel):
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    format: str | None = None
    bitdepth: int | None = None
    compression: str | None = None
    size_label: str | None = None


class ResourceMetricSummary(BaseModel):
    power_mw: float | None = None
    bw_read_mbs: float | None = None
    bw_write_mbs: float | None = None
    bw_total_mbs: float | None = None
    hw_time_ms: float | None = None
    evidence_id: str | None = None


class ResourceOverviewRow(BaseModel):
    sequence_index: int
    node_id: str
    label: str
    resource_domain: Literal["external_source", "soc_resource", "memory", "external_sink"]
    resource_kind: str
    subsystem: str
    role: str | None = None
    input: IoSummary | None = None
    output: IoSummary | None = None
    flow: Literal["OTF", "vOTF", "M2M", "control", "risk", "mixed", "none"] = "none"
    buffer_refs: list[str] = []
    input_buffer_refs: list[str] = []
    status: Literal["active", "inactive", "warning", "blocked"] = "active"
    badges: list[str] = []
    metrics: ResourceMetricSummary | None = None
    detail_items: list[str] = []


class BufferHandoffSummary(BaseModel):
    buffer_ref: str
    subsystem: str
    producer_node_id: str | None = None
    consumer_node_ids: list[str] = []
    size_label: str | None = None
    format: str | None = None
    bitdepth: int | None = None
    compression: str | None = None
    comp_ratio: float | None = None
    llc_allocated: bool = False
    llc_policy: str | None = None
    llc_allocation_mb: float | None = None


class DisplayLayerSummary(BaseModel):
    name: str
    buffer_ref: str | None = None
    format: str | None = None
    src_frame: str | None = None
    dst_frame: str | None = None
    transform: str | None = None
    alpha: float | None = None


class DisplayCompositionSummary(BaseModel):
    node_id: str
    composer: str | None = None
    layer_count: int | None = None
    panel_mode: str | None = None
    output: IoSummary | None = None
    layers: list[DisplayLayerSummary] = []


class SensorEndpointSummary(BaseModel):
    node_id: str
    sensor_mode: str | None = None
    module_ref: str | None = None
    output: IoSummary | None = None
    downstream: list[str] = []


class Level0MetricBreakdown(BaseModel):
    subsystem: str
    power_mw: float | None = None
    bw_total_mbs: float | None = None
    hw_time_ms: float | None = None
    node_count: int = 0
    warning_count: int = 0


class Level0ResourceOverview(BaseModel):
    rows: list[ResourceOverviewRow] = []
    buffers: list[BufferHandoffSummary] = []
    metric_breakdown: list[Level0MetricBreakdown] = []
    sensors: list[SensorEndpointSummary] = []
    displays: list[DisplayCompositionSummary] = []
    notes: list[str] = []


class NodeData(BaseModel):
    id: str
    label: str
    type: Literal["sw", "ip", "submodule", "buffer", "dma_group", "dma_channel", "sysmmu",
                  "lane_bg", "lane_label", "stage_header"]
    layer: Literal["app", "framework", "hal", "kernel", "external", "hw", "memory", "meta"] = "meta"
    parent: str | None = None
    ip_ref: str | None = None
    sw_ref: str | None = None
    hierarchy_group: str | None = None
    ip_group: str | None = None
    dvfs_group: str | None = None
    role_hw_name: str | None = None
    semantic_source: str | None = None
    module_ref: str | None = None
    module_kind: str | None = None
    module_direction: str | None = None
    module_status: str | None = None
    port_ref: str | None = None
    summary_badges: list[str] = []
    capability_badges: list[str] = []
    active_operations: OperationSummary | None = None
    memory: MemoryDescriptor | None = None
    placement: MemoryPlacement | None = None
    dma_count: int | None = None
    shared_resource: bool = False
    matched_issues: list[str] = []
    detail_items: list[str] = []
    severity: str | None = None
    warning: bool = False
    collapsed_children_count: int = 0
    view_hints: ViewHints | None = None
    sim_overlay: SimOverlay | None = None


class NodeElement(BaseModel):
    data: NodeData
    position: dict[str, float]


class ViewPortPair(BaseModel):
    """Producer/consumer port names carried by an edge (WDMA->RDMA, FIFO pair)."""

    src: str
    dst: str


class EdgeData(BaseModel):
    id: str
    source: str
    target: str
    flow_type: Literal["OTF", "vOTF", "M2M", "control", "risk"]
    latency_class: Literal["streaming", "line_delayed", "frame_buffered"] | None = None
    buffer_ref: str | None = None
    producer: str | None = None
    consumer: str | None = None
    port_pairs: list[ViewPortPair] = []
    memory: MemoryDescriptor | None = None
    placement: MemoryPlacement | None = None
    sim_overlay: EdgeSimOverlay | None = None
    label: str | None = None
    detail_items: list[str] = []
    # Both endpoints on the simulated critical path (set by the sim overlay).
    # None (not False) by default so plain projections serialize unchanged.
    critical: bool | None = None


class EdgeElement(BaseModel):
    data: EdgeData


class RiskCard(BaseModel):
    id: str
    title: str
    component: str
    description: str
    severity: Literal["Critical", "High", "Medium", "Low"]
    impact: str


class ViewSummary(BaseModel):
    scenario_id: str
    variant_id: str
    name: str
    subtitle: str
    period_ms: float
    budget_ms: float
    resolution: str
    fps: int
    variant_label: str
    notes: str | None = None
    captured_at: str | None = None


class ViewResponse(BaseModel):
    level: int
    mode: str | None = None
    scenario_id: str
    variant_id: str
    nodes: list[NodeElement]
    edges: list[EdgeElement]
    risks: list[RiskCard] = []
    summary: ViewSummary
    metadata: dict = {}
    overlays_available: list[str] = []
    level0_resource_overview: Level0ResourceOverview | None = None
