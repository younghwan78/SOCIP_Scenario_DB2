"""Buffer and memory helpers for view projections."""
from __future__ import annotations

from typing import Any

from scenario_db.api.schemas.view import MemoryDescriptor, MemoryPlacement
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.graph_utils import parse_size as _parse_size, resolution_to_size as _resolution_to_size

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

def _buffer_label(buffer_ref: str) -> str:
    return str(buffer_ref).replace("_", " ").title()

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
