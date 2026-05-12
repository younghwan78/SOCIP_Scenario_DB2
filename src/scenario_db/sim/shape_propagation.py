from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.external_devices import selected_sensor_mode
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type


@dataclass(frozen=True, slots=True)
class SurfaceShape:
    width: int = 0
    height: int = 0
    format: str | None = None
    bitwidth: int | None = None
    compression: str | None = None
    source: str | None = None

    @property
    def valid_size(self) -> bool:
        return self.width > 0 and self.height > 0

    def with_fallback(self, fallback: SurfaceShape) -> SurfaceShape:
        return SurfaceShape(
            width=self.width or fallback.width,
            height=self.height or fallback.height,
            format=self.format or fallback.format,
            bitwidth=self.bitwidth or fallback.bitwidth,
            compression=self.compression or fallback.compression,
            source=self.source or fallback.source,
        )


@dataclass(frozen=True, slots=True)
class NodeShape:
    node_id: str
    input: SurfaceShape
    output: SurfaceShape


@dataclass(frozen=True, slots=True)
class PropagatedShapes:
    nodes: dict[str, NodeShape]
    buffers: dict[str, SurfaceShape]

    def node(self, node_id: str) -> NodeShape | None:
        return self.nodes.get(node_id)

    def buffer(self, buffer_id: str | None) -> SurfaceShape | None:
        return self.buffers.get(str(buffer_id)) if buffer_id else None


def propagate_shapes(graph: CanonicalScenarioGraph) -> PropagatedShapes:
    """Infer node and buffer width/height/format along the effective topology."""

    node_ids = [str(node.get("id")) for node in graph.pipeline_nodes if node.get("id")]
    nodes = {
        node_id: NodeShape(node_id=node_id, input=SurfaceShape(), output=SurfaceShape())
        for node_id in node_ids
    }
    buffers = _initial_buffer_shapes(graph)
    design = _design_shape(graph)

    for node in graph.pipeline_nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        sim = _node_sim_block(graph, node_id)
        explicit_input = _first_port_shape(sim.get("inputs") or [], source=f"{node_id}.sim.inputs")
        explicit_output = _first_port_shape(sim.get("outputs") or [], source=f"{node_id}.sim.outputs")
        source_shape = _sensor_source_shape(graph, node)
        current = nodes[node_id]
        input_shape = explicit_input.with_fallback(current.input)
        output_shape = explicit_output.with_fallback(source_shape).with_fallback(current.output)
        nodes[node_id] = NodeShape(node_id=node_id, input=input_shape, output=output_shape)

    # A few passes are enough for DAG-like camera/display topologies and keep
    # this independent from NetworkX for simple unit-test usage.
    for _ in range(max(1, len(nodes) + len(graph.pipeline_edges))):
        changed = False
        for edge in graph.pipeline_edges:
            source = str(edge_source(edge) or "")
            target = str(edge_target(edge) or "")
            if source not in nodes or target not in nodes:
                continue
            transfer_shape = _edge_transfer_shape(graph, edge, nodes[source].output, buffers, design)
            if not transfer_shape.valid_size and not transfer_shape.format:
                continue

            if edge.get("buffer"):
                buffer_id = str(edge["buffer"])
                existing = buffers.get(buffer_id, SurfaceShape())
                merged = existing.with_fallback(transfer_shape)
                if merged != existing:
                    buffers[buffer_id] = merged
                    changed = True

            target_shape = nodes[target]
            merged_input = target_shape.input.with_fallback(transfer_shape)
            transformed_output = _apply_node_transform(graph, target, merged_input).with_fallback(target_shape.output)
            updated = NodeShape(node_id=target, input=merged_input, output=transformed_output)
            if updated != target_shape:
                nodes[target] = updated
                changed = True
        if not changed:
            break

    for node_id, shape in list(nodes.items()):
        if not shape.input.valid_size and not shape.output.valid_size and design.valid_size:
            nodes[node_id] = NodeShape(
                node_id=node_id,
                input=shape.input.with_fallback(design),
                output=shape.output.with_fallback(design),
            )
    return PropagatedShapes(nodes=nodes, buffers=buffers)


def shape_from_port(port: dict[str, Any], *, source: str | None = None) -> SurfaceShape:
    width, height = _size_tuple(port.get("size"))
    width = int(port.get("width") or port.get("w") or width or 0)
    height = int(port.get("height") or port.get("h") or height or 0)
    return SurfaceShape(
        width=width,
        height=height,
        format=port.get("format"),
        bitwidth=_int_or_none(port.get("bitwidth") or port.get("bitdepth")),
        compression=port.get("compression") or port.get("comp"),
        source=source,
    )


def shape_to_port_defaults(shape: SurfaceShape) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if shape.width:
        result["width"] = shape.width
    if shape.height:
        result["height"] = shape.height
    if shape.format:
        result["format"] = shape.format
    if shape.bitwidth:
        result["bitwidth"] = shape.bitwidth
    if shape.compression:
        result["compression"] = shape.compression
    return result


def _initial_buffer_shapes(graph: CanonicalScenarioGraph) -> dict[str, SurfaceShape]:
    result: dict[str, SurfaceShape] = {}
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    overrides = graph.variant.buffer_overrides or {}
    for buffer_id, buffer in buffers.items():
        descriptor = dict(buffer or {})
        if isinstance(overrides.get(buffer_id), dict):
            descriptor.update(overrides[buffer_id])
        result[str(buffer_id)] = _shape_from_buffer(graph, str(buffer_id), descriptor)
    return result


def _shape_from_buffer(graph: CanonicalScenarioGraph, buffer_id: str, buffer: dict[str, Any]) -> SurfaceShape:
    width, height = _size_tuple(buffer.get("size"))
    if not width or not height:
        size_ref = buffer.get("size_ref")
        if size_ref:
            variant_size = (graph.variant.size_overrides or {}).get(size_ref)
            anchors = (graph.scenario.size_profile or {}).get("anchors") or {}
            width, height = _size_tuple(variant_size or anchors.get(size_ref))
    return SurfaceShape(
        width=width,
        height=height,
        format=buffer.get("format"),
        bitwidth=_int_or_none(buffer.get("bitwidth") or buffer.get("bitdepth")),
        compression=buffer.get("compression"),
        source=f"buffer.{buffer_id}",
    )


def _edge_transfer_shape(
    graph: CanonicalScenarioGraph,
    edge: dict[str, Any],
    source_output: SurfaceShape,
    buffers: dict[str, SurfaceShape],
    design: SurfaceShape,
) -> SurfaceShape:
    buffer_shape = buffers.get(str(edge.get("buffer"))) if edge.get("buffer") else None
    if edge_type(edge) in {"M2M", "vOTF"} and buffer_shape:
        return buffer_shape.with_fallback(source_output).with_fallback(design)
    return source_output.with_fallback(buffer_shape or SurfaceShape()).with_fallback(design)


def _sensor_source_shape(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> SurfaceShape:
    ip_ref = str(node.get("ip_ref") or "")
    ip_row = graph.ip_catalog.get(ip_ref)
    if ip_row is None:
        return SurfaceShape()
    category = str(getattr(ip_row, "category", "") or "").lower()
    if category != "sensor" and "sensor" not in str(node.get("role") or node.get("id") or "").lower():
        return SurfaceShape()
    mode = selected_sensor_mode(graph, node) or {}
    active_size = mode.get("active_size") or mode.get("sensor_size")
    width, height = _size_tuple(active_size)
    return SurfaceShape(
        width=width,
        height=height,
        format=mode.get("sensor_format"),
        bitwidth=_int_or_none(mode.get("sensor_bitwidth")),
        compression=mode.get("sensor_sbwc"),
        source=f"{node.get('id')}.sensor_mode",
    )


def _apply_node_transform(graph: CanonicalScenarioGraph, node_id: str, input_shape: SurfaceShape) -> SurfaceShape:
    sim = _node_sim_block(graph, node_id)
    output_size = (
        sim.get("output_size")
        or sim.get("scale_size")
        or sim.get("target_size")
        or sim.get("size")
    )
    width, height = _size_tuple(output_size)
    crop = sim.get("crop") if isinstance(sim.get("crop"), dict) else {}
    scale = sim.get("scale") if isinstance(sim.get("scale"), dict) else {}
    width = int(sim.get("output_width") or sim.get("width_out") or scale.get("width") or scale.get("w") or crop.get("width") or crop.get("w") or width or input_shape.width)
    height = int(sim.get("output_height") or sim.get("height_out") or scale.get("height") or scale.get("h") or crop.get("height") or crop.get("h") or height or input_shape.height)
    return replace(
        input_shape,
        width=width,
        height=height,
        format=sim.get("output_format") or sim.get("format") or input_shape.format,
        bitwidth=_int_or_none(sim.get("output_bitwidth") or sim.get("bitwidth")) or input_shape.bitwidth,
        compression=sim.get("output_compression") or sim.get("compression") or input_shape.compression,
        source=f"{node_id}.shape_transform" if width or height else input_shape.source,
    )


def _node_sim_block(graph: CanonicalScenarioGraph, node_id: str) -> dict[str, Any]:
    config = (graph.variant.node_configs or {}).get(node_id) or {}
    sim = config.get("sim") or {}
    return sim if isinstance(sim, dict) else {}


def _first_port_shape(ports: list[dict[str, Any]], *, source: str) -> SurfaceShape:
    for port in ports:
        if not isinstance(port, dict):
            continue
        shape = shape_from_port(port, source=source)
        if shape.valid_size or shape.format:
            return shape
    return SurfaceShape()


def _design_shape(graph: CanonicalScenarioGraph) -> SurfaceShape:
    design = graph.variant.design_conditions or {}
    for key in ("size", "resolution_size", "output_size"):
        width, height = _size_tuple(design.get(key))
        if width and height:
            return SurfaceShape(width=width, height=height, format=design.get("format") or design.get("pixel_format"), source=f"design.{key}")
    resolution = str(design.get("resolution") or "").upper()
    mapping = {
        "FHD": (1920, 1080),
        "QHD": (2560, 1440),
        "UHD": (3840, 2160),
        "4K": (3840, 2160),
        "8K": (7680, 4320),
    }
    width, height = mapping.get(resolution, (0, 0))
    return SurfaceShape(width=width, height=height, format=design.get("format") or design.get("pixel_format"), source="design.resolution" if width else None)


def _size_tuple(value: Any) -> tuple[int, int]:
    if isinstance(value, str) and "x" in value.lower():
        left, right = value.lower().split("x", 1)
        try:
            return int(left), int(right)
        except ValueError:
            return 0, 0
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0] or 0), int(value[1] or 0)
        except (TypeError, ValueError):
            return 0, 0
    return 0, 0


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
