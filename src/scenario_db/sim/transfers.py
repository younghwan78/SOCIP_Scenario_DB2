from __future__ import annotations

from typing import Any, cast

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.bw_calc import compression_enabled, normalize_compression, resolve_comp_ratio
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.models import IPWorkload, PortTransferSpec, PortType
from scenario_db.sim.shape_propagation import NodeShape, SurfaceShape
from scenario_db.sim.workloads import buffer_size, design_size_for_graph, port_size


def compression_catalog(soc: object | None) -> dict[str, float]:
    """Extract {mode_name: comp_ratio} from a SoC's compression_modes catalog.

    Tolerates both the ORM row (dict-of-dict JSONB) and a pydantic SocPlatform
    (dict-of-CompressionMode), so sim works with or without a DB-backed graph.
    """
    modes = getattr(soc, "compression_modes", None) or {}
    catalog: dict[str, float] = {}
    for name, entry in modes.items():
        ratio = entry.get("comp_ratio") if isinstance(entry, dict) else getattr(entry, "comp_ratio", None)
        if ratio is not None:
            catalog[str(name)] = float(ratio)
    return catalog


def _resolve_port_comp_ratio(
    compression: str,
    raw_override: object,
    catalog: dict[str, float] | None,
    warnings: list[str] | None,
    where: str,
) -> float:
    if raw_override is not None and not isinstance(raw_override, (int, float, str)):
        raise ValueError(f"{where}: comp_ratio must be numeric")
    override = float(raw_override) if raw_override is not None else None
    if override is not None and warnings is not None and catalog and compression_enabled(compression):
        mode = normalize_compression(compression)
        catalog_ratio = catalog.get(mode) if mode else None
        if catalog_ratio is not None and float(catalog_ratio) != override:
            warnings.append(
                f"{where}: comp_ratio override {override} differs from catalog "
                f"{catalog_ratio} for '{mode}'"
            )
    return resolve_comp_ratio(compression, catalog, override=override)


def port_transfers_for_node(
    node_id: str,
    ip_ref: str,
    hw_name: str,
    sim_block: dict[str, Any],
    *,
    shape: NodeShape | None = None,
    comp_catalog: dict[str, float] | None = None,
    warnings: list[str] | None = None,
) -> list[PortTransferSpec]:
    specs: list[PortTransferSpec] = []
    for key, default_type in (("inputs", PortType.DMA_READ), ("outputs", PortType.DMA_WRITE)):
        for port in sim_block.get(key) or []:
            width, height = port_size(port)
            fallback_shape = _port_fallback_shape(default_type, shape, port) if _use_propagated_shape(sim_block) else None
            if (width == 0 or height == 0) and fallback_shape:
                width, height = fallback_shape.width, fallback_shape.height
            port_type = port_type_for_config(port, default_type)
            port_name = str(port.get("port") or port.get("name") or key)
            compression = str(port.get("compression") or port.get("comp") or (fallback_shape.compression if fallback_shape else None) or "disable")
            comp_ratio = _resolve_port_comp_ratio(
                compression, port.get("comp_ratio"), comp_catalog, warnings, f"{node_id}.{port_name}"
            )
            specs.append(
                PortTransferSpec(
                    node_id=node_id,
                    ip_ref=ip_ref,
                    hw_name=hw_name,
                    port=port_name,
                    port_type=port_type,
                    width=width,
                    height=height,
                    format=port.get("format") or (fallback_shape.format if fallback_shape else None),
                    bitwidth=int(port.get("bitwidth") or port.get("bitdepth") or (fallback_shape.bitwidth if fallback_shape else 8) or 8),
                    compression=compression,
                    comp_ratio=comp_ratio,
                    comp_ratio_min=port.get("comp_ratio_min"),
                    comp_ratio_max=port.get("comp_ratio_max"),
                    llc_enabled=enabled(port.get("llc_enabled", port.get("llc_enable", False))),
                    llc_weight=float(port.get("llc_weight") or 1.0),
                    r_w_rate=float(port.get("r_w_rate") or 1.0),
                )
            )
    return specs


def _port_fallback_shape(
    default_type: PortType,
    shape: NodeShape | None,
    port: dict[str, Any],
) -> SurfaceShape | None:
    if shape is None:
        return None
    port_name = port.get("port") or port.get("name") or port.get("port_type") or port.get("type")
    if default_type == PortType.DMA_READ:
        return shape.input_port(str(port_name)) or shape.input
    return shape.output_port(str(port_name)) or shape.output


def _use_propagated_shape(sim_block: dict[str, Any]) -> bool:
    return bool(sim_block.get("inherit_shape") or sim_block.get("shape_propagation"))


def _effective_buffer(graph: CanonicalScenarioGraph, buffer_id: str) -> dict[str, Any]:
    base = (cast(dict[str, Any], graph.scenario.pipeline or {}).get("buffers") or {}).get(buffer_id) or {}
    override = (graph.variant.buffer_overrides or {}).get(buffer_id) or {}
    return {**base, **override}


def _buffer_transfers(
    graph: CanonicalScenarioGraph,
    workload: IPWorkload,
    buffer_id: str,
    names: list[str],
    direction: PortType,
    comp_catalog: dict[str, float] | None,
    warnings: list[str] | None,
) -> list[PortTransferSpec]:
    buffer = _effective_buffer(graph, buffer_id)
    width, height = buffer_size(graph, buffer)
    if width == 0 or height == 0:
        width, height = design_size_for_graph(graph)
    if width == 0 or height == 0:
        return []
    compression = str(buffer.get("compression") or "disable")
    comp_ratio = _resolve_port_comp_ratio(
        compression, buffer.get("comp_ratio"), comp_catalog, warnings, f"buffer.{buffer_id}"
    )
    fmt = buffer.get("format")
    # A planar YUV444 buffer has three full-size single-component planes.
    # Names remain physical driver DMA identifiers while BW counts each plane once.
    if len(names) == 3 and str(fmt).upper() == "YUV444":
        fmt = "Y"
    return [PortTransferSpec(
        node_id=workload.node_id, ip_ref=workload.ip_ref, hw_name=workload.hw_name,
        port=name, port_type=direction, width=width, height=height,
        format=fmt, bitwidth=int(buffer.get("bitdepth") or 8),
        compression=compression, comp_ratio=comp_ratio,
    ) for name in names]


def edge_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
    *,
    comp_catalog: dict[str, float] | None = None,
    warnings: list[str] | None = None,
) -> list[PortTransferSpec]:
    specs: list[PortTransferSpec] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in graph.pipeline_edges:
        if edge_type(edge) != "M2M":
            continue
        source, target = str(edge_source(edge) or ""), str(edge_target(edge) or "")
        buffer_id = str(edge.get("buffer") or "")
        pairs = edge.get("port_pairs") or []
        for node_id, direction, key, fallback in (
            (source, PortType.DMA_WRITE, "src", f"{buffer_id or target}_WDMA"),
            (target, PortType.DMA_READ, "dst", f"{buffer_id or source}_RDMA"),
        ):
            if node_id not in workloads:
                continue
            names = list(dict.fromkeys(str(pair[key]) for pair in pairs if pair.get(key))) or [fallback]
            for spec in _buffer_transfers(graph, workloads[node_id], buffer_id, names, direction, comp_catalog, warnings):
                identity = (node_id, spec.port, buffer_id, direction)
                # Fan-out from the same MCSC buffer writes once, reads once per consumer.
                if identity not in seen:
                    seen.add(identity)
                    specs.append(spec)
    return specs


def history_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
    comp_catalog: dict[str, float] | None = None,
    warnings: list[str] | None = None,
) -> list[PortTransferSpec]:
    """Steady-state previous-frame traffic without a same-frame DAG self-cycle."""
    specs = []
    for buffer_id in (cast(dict[str, Any], graph.scenario.pipeline or {}).get("buffers") or {}):
        history = _effective_buffer(graph, buffer_id).get("history") or {}
        node_id = str(history.get("node_id") or "")
        if node_id not in workloads:
            continue
        if history.get("frame_offset") != -1:
            raise ValueError(f"{buffer_id}: history requires frame_offset=-1")
        for key, direction in (("read_ports", PortType.DMA_READ), ("write_ports", PortType.DMA_WRITE)):
            specs.extend(_buffer_transfers(graph, workloads[node_id], buffer_id, history.get(key) or [], direction, comp_catalog, warnings))
    return specs


def port_type_for_config(port: dict[str, Any], default: PortType) -> PortType:
    explicit = port.get("port_type") or port.get("type")
    if explicit:
        return PortType(str(explicit))
    name = str(port.get("port") or port.get("name") or "").upper()
    if "RDMA" in name:
        return PortType.DMA_READ
    if "WDMA" in name:
        return PortType.DMA_WRITE
    if "FIFO" in name or "OTF" in name:
        return PortType.OTF_IN if default == PortType.DMA_READ else PortType.OTF_OUT
    return default


def enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"enable", "enabled", "true", "1", "yes"}
