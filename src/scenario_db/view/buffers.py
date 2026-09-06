"""Buffer and memory helpers for view projections."""
from __future__ import annotations

from typing import Any

from scenario_db.api.schemas.view import MemoryDescriptor, MemoryPlacement
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.bw_calc import normalize_compression
from scenario_db.view.graph_utils import parse_size as _parse_size, resolution_to_size as _resolution_to_size

_OFF_DISPLAY = "COMP_OFF"


def display_compression(value: Any) -> str | None:
    """Canonical compression label for views.

    Unspecified compression stays None (no badge). Any 'off' spelling
    (none/disable/off/COMP_OFF) renders uniformly as COMP_OFF; a real mode
    passes through unchanged. Shares the off-detection SSOT with the sim layer.
    """
    if value is None:
        return None
    return value if normalize_compression(value) is not None else _OFF_DISPLAY

def _reference_sizes(graph: CanonicalScenarioGraph) -> dict[str, str]:
    design = graph.variant.design_conditions or {}
    size_profile = graph.scenario.size_profile or {}
    anchors = size_profile.get("anchors") or {}
    overrides = getattr(graph.variant, "size_overrides", None) or {}
    sensor = overrides.get("sensor_full") or anchors.get("sensor_full") or "4000x3000"
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
    width, height = _buffer_spec_size(graph, spec, tokens)
    return MemoryDescriptor(
        format=spec.get("format"),
        bitdepth=spec.get("bitdepth"),
        planes=spec.get("planes"),
        width=width,
        height=height,
        fps=int(tokens.get("fps", "30")),
        alignment=spec.get("alignment"),
        compression=display_compression(spec.get("compression")),
    )


def _buffer_spec_size(
    graph: CanonicalScenarioGraph,
    spec: dict[str, Any],
    tokens: dict[str, str],
) -> tuple[int | None, int | None]:
    """Resolve a buffer's WxH: explicit size -> size_ref token -> explicit
    width/height -> format-aware scenario anchors (RAW/Bayer buffers default
    to the sensor size, everything else to the record/preview output).

    The anchor fallback mirrors Level 0's table sizing so edge descriptors and
    the resource overview agree even when fixtures omit size_ref.
    """

    if spec.get("size"):
        width, height = _parse_size(str(spec["size"]))
        if width and height:
            return width, height
    size_ref = spec.get("size_ref")
    if size_ref:
        width, height = _parse_size(tokens.get(str(size_ref), str(size_ref)))
        if width and height:
            return width, height
    if spec.get("width") and spec.get("height"):
        try:
            return int(spec["width"]), int(spec["height"])
        except (TypeError, ValueError):
            pass
    format_text = str(spec.get("format") or "").lower()
    if "raw" in format_text or "bayer" in format_text:
        keys = ("sensor_full", "record_out", "preview_out")
    else:
        keys = ("record_out", "preview_out", "sensor_full")
    for key in keys:
        width, height = _parse_size(tokens.get(key, ""))
        if width and height:
            return width, height
    return None, None

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
        comp_text = display_compression(spec.get("compression"))
        comp_ratio = spec.get("comp_ratio") or spec.get("compression_ratio")
        if comp_text and comp_ratio and normalize_compression(spec.get("compression")) is not None:
            comp_text = f"{comp_text}({comp_ratio})"
        bits = [
            spec.get("format"),
            _size_text(spec.get("size_ref") or spec.get("size")),
            f"{spec.get('bitdepth')}b" if spec.get("bitdepth") is not None else None,
            comp_text,
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
        compression=_compression_for_buffer(graph, buffer_ref),
    )

def _memory_placement(graph: CanonicalScenarioGraph, buffer_ref: str) -> MemoryPlacement:
    # IP requirements describe capacity requirements, not per-buffer placement.
    # Only an authored placement is evidence that this buffer uses LLC.
    spec = _buffer_spec(graph, buffer_ref)
    if spec.get("placement"):
        return MemoryPlacement(**spec["placement"])
    return MemoryPlacement()

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

def _compression_for_buffer(graph: CanonicalScenarioGraph, buffer_ref: str) -> str | None:
    """Fallback compression for a buffer with no explicit spec.

    Attribute to the buffer's *producing* IP (the edge source), not an arbitrary
    catalog entry, and prefer a real (enabled) mode the producer supports.
    Returns None when the producer is unknown or declares no compression.
    """
    for edge in getattr(graph, "pipeline_edges", None) or []:
        if not isinstance(edge, dict) or str(edge.get("buffer") or "") != buffer_ref:
            continue
        source = edge.get("from") or edge.get("src") or edge.get("source")
        node = graph.node_by_id(str(source)) if source else None
        ip_row = graph.ip_catalog.get((node or {}).get("ip_ref")) if node else None
        caps = (ip_row.capabilities if ip_row else None) or {}
        modes = list((caps.get("supported_features") or {}).get("compression") or [])
        for module in (caps.get("properties") or {}).get("modules") or []:
            if isinstance(module, dict):
                modes.extend(module.get("supported_compressions") or [])
        for mode in modes:
            if normalize_compression(mode) is not None:
                return str(mode)
    return None
