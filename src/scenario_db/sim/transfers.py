from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.models import IPWorkload, PortTransferSpec, PortType
from scenario_db.sim.shape_propagation import NodeShape, SurfaceShape
from scenario_db.sim.workloads import buffer_size, design_size_for_graph, port_size


def port_transfers_for_node(
    node_id: str,
    ip_ref: str,
    hw_name: str,
    sim_block: dict[str, Any],
    *,
    shape: NodeShape | None = None,
) -> list[PortTransferSpec]:
    specs: list[PortTransferSpec] = []
    for key, default_type in (("inputs", PortType.DMA_READ), ("outputs", PortType.DMA_WRITE)):
        for port in sim_block.get(key) or []:
            width, height = port_size(port)
            fallback_shape = _port_fallback_shape(default_type, shape) if _use_propagated_shape(sim_block) else None
            if (width == 0 or height == 0) and fallback_shape:
                width, height = fallback_shape.width, fallback_shape.height
            port_type = port_type_for_config(port, default_type)
            specs.append(
                PortTransferSpec(
                    node_id=node_id,
                    ip_ref=ip_ref,
                    hw_name=hw_name,
                    port=str(port.get("port") or port.get("name") or key),
                    port_type=port_type,
                    width=width,
                    height=height,
                    format=port.get("format") or (fallback_shape.format if fallback_shape else None),
                    bitwidth=int(port.get("bitwidth") or port.get("bitdepth") or (fallback_shape.bitwidth if fallback_shape else 8) or 8),
                    compression=str(port.get("compression") or port.get("comp") or (fallback_shape.compression if fallback_shape else None) or "disable"),
                    comp_ratio=float(port.get("comp_ratio") or 1.0),
                    comp_ratio_min=port.get("comp_ratio_min"),
                    comp_ratio_max=port.get("comp_ratio_max"),
                    llc_enabled=enabled(port.get("llc_enabled", port.get("llc_enable", False))),
                    llc_weight=float(port.get("llc_weight") or 1.0),
                    r_w_rate=float(port.get("r_w_rate") or 1.0),
                )
            )
    return specs


def _port_fallback_shape(default_type: PortType, shape: NodeShape | None) -> SurfaceShape | None:
    if shape is None:
        return None
    return shape.input if default_type == PortType.DMA_READ else shape.output


def _use_propagated_shape(sim_block: dict[str, Any]) -> bool:
    return bool(sim_block.get("inherit_shape") or sim_block.get("shape_propagation"))


def edge_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
) -> list[PortTransferSpec]:
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    specs: list[PortTransferSpec] = []
    for edge in graph.pipeline_edges:
        if edge_type(edge) != "M2M":
            continue
        source = str(edge_source(edge) or "")
        target = str(edge_target(edge) or "")
        buffer = buffers.get(edge.get("buffer")) if edge.get("buffer") else {}
        width, height = buffer_size(graph, buffer) if isinstance(buffer, dict) else (0, 0)
        if width == 0 or height == 0:
            width, height = design_size_for_graph(graph)
        if width == 0 or height == 0:
            continue
        bitwidth = int(buffer.get("bitdepth") or 8) if isinstance(buffer, dict) else 8
        compression = str(buffer.get("compression") or "disable") if isinstance(buffer, dict) else "disable"
        fmt = buffer.get("format") if isinstance(buffer, dict) else None
        if source in workloads:
            workload = workloads[source]
            specs.append(
                PortTransferSpec(
                    node_id=source,
                    ip_ref=workload.ip_ref,
                    hw_name=workload.hw_name,
                    port=f"{edge.get('buffer') or target}_WDMA",
                    port_type=PortType.DMA_WRITE,
                    width=width,
                    height=height,
                    format=fmt,
                    bitwidth=bitwidth,
                    compression=compression,
                )
            )
        if target in workloads:
            workload = workloads[target]
            specs.append(
                PortTransferSpec(
                    node_id=target,
                    ip_ref=workload.ip_ref,
                    hw_name=workload.hw_name,
                    port=f"{edge.get('buffer') or source}_RDMA",
                    port_type=PortType.DMA_READ,
                    width=width,
                    height=height,
                    format=fmt,
                    bitwidth=bitwidth,
                    compression=compression,
                )
            )
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
