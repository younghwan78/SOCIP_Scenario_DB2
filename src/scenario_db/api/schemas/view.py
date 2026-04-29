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


class NodeData(BaseModel):
    id: str
    label: str
    type: Literal["sw", "ip", "submodule", "buffer", "dma_group", "dma_channel", "sysmmu",
                  "lane_bg", "lane_label", "stage_header"]
    layer: Literal["app", "framework", "hal", "kernel", "hw", "memory", "meta"] = "meta"
    parent: str | None = None
    ip_ref: str | None = None
    sw_ref: str | None = None
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


class NodeElement(BaseModel):
    data: NodeData
    position: dict[str, float]


class EdgeData(BaseModel):
    id: str
    source: str
    target: str
    flow_type: Literal["OTF", "vOTF", "M2M", "control", "risk"]
    latency_class: Literal["streaming", "line_delayed", "frame_buffered"] | None = None
    buffer_ref: str | None = None
    producer: str | None = None
    consumer: str | None = None
    memory: MemoryDescriptor | None = None
    placement: MemoryPlacement | None = None
    label: str | None = None
    detail_items: list[str] = []


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
