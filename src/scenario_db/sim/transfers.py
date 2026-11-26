from __future__ import annotations

import math
from typing import Any, Literal, cast

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.bw_calc import compression_enabled, normalize_compression, resolve_comp_ratio
from scenario_db.sim.constants import BPP_DEFAULT, format_bpp_factor
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.models import IPSimParams, IPWorkload, PortTransferSpec, PortType
from scenario_db.sim.shape_propagation import NodeShape, SurfaceShape
from scenario_db.sim.workloads import buffer_size, design_size_for_graph, port_size


def compression_catalog(soc: object | None, purpose: Literal["mean", "peak"] = "peak") -> dict[str, float]:
    """Extract {mode_name: ratio} from a SoC's compression_modes catalog.

    ``purpose="peak"`` returns the catalog ``comp_ratio`` (worst case, BW allocation);
    ``purpose="mean"`` prefers ``typical_ratio`` (average, power / mean BW) and falls back to
    ``comp_ratio``. The engine baseline, What-if and exploration all price power with "mean", so
    re-selecting the current mode is a no-op and switching an SBWC buffer off costs BW.

    Tolerates both the ORM row (dict-of-dict JSONB) and a pydantic SocPlatform
    (dict-of-CompressionMode), so sim works with or without a DB-backed graph.
    """
    modes = getattr(soc, "compression_modes", None) or {}
    catalog: dict[str, float] = {}
    for name, entry in modes.items():
        get = entry.get if isinstance(entry, dict) else (lambda k, e=entry: getattr(e, k, None))
        ratio = get("comp_ratio")
        if purpose == "mean" and get("typical_ratio") is not None:
            ratio = get("typical_ratio")
        if ratio is not None:
            catalog[str(name)] = float(ratio)
    return catalog


def apply_peak_ratio(specs: list[PortTransferSpec], peak: dict[str, float]) -> list[PortTransferSpec]:
    """Attach the catalog worst-case ratio as ``comp_ratio_max`` (-> ``bw_mbs_worst``) where it exceeds the mean."""
    out = []
    for spec in specs:
        mode = normalize_compression(spec.compression)
        worst = peak.get(mode) if mode else None
        if worst is not None and spec.comp_ratio_max is None and worst > spec.comp_ratio:
            spec = spec.model_copy(update={"comp_ratio_max": worst})
        out.append(spec)
    return out


def compression_typical(soc: object | None) -> dict[str, float]:
    """{mode_name: typical_ratio} for modes that declare an average ratio (power / mean BW), else nothing."""
    modes = getattr(soc, "compression_modes", None) or {}
    out: dict[str, float] = {}
    for name, entry in modes.items():
        ratio = entry.get("typical_ratio") if isinstance(entry, dict) else getattr(entry, "typical_ratio", None)
        if ratio is not None:
            out[str(name)] = float(ratio)
    return out


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
    merged = {**base, **override}
    for key in ("dma", "history", "placement"):
        if isinstance(override.get(key), dict):
            merged[key] = {**(base.get(key) or {}), **override[key]}
    return merged


def _buffer_transfers(
    graph: CanonicalScenarioGraph,
    workload: IPWorkload,
    buffer_id: str,
    names: list[str],
    direction: PortType,
    comp_catalog: dict[str, float] | None,
    warnings: list[str] | None,
    rate: float = 1.0,
    fallback_size: tuple[int, int] | None = None,
) -> list[PortTransferSpec]:
    buffer = _effective_buffer(graph, buffer_id)
    if getattr(workload, "mode", None) == DMA_ONLY and str(buffer.get("format") or "").upper() == "BITSTREAM":
        return _bitstream_transfers(graph, workload, buffer_id, buffer, names, direction, rate, warnings)
    if buffer.get("size_status") == "unknown":
        if warnings is not None and names:
            message = f"{buffer_id}: DMA size/format unknown; excluded from bandwidth totals."
            if message not in warnings:
                warnings.append(message)
        return []
    width, height = buffer_size(graph, buffer)
    if width == 0 or height == 0:
        width, height = design_size_for_graph(graph)
    if (width == 0 or height == 0) and fallback_size:
        # R-5b: no anchor and no design resolution: the producer's declared surface (sim width/height, else the
        # scaler dst) - only where the buffer was dropped before, so sized buffers keep their values
        width, height = fallback_size
    if width == 0 or height == 0:
        if warnings is not None and names:
            message = (f"{buffer_id}: no size (size_ref / design resolution); its DMA is excluded from bandwidth "
                       "totals.")
            if message not in warnings:
                warnings.append(message)
        return []
    compression = str(buffer.get("compression") or "disable")
    comp_ratio = _resolve_port_comp_ratio(
        compression, buffer.get("comp_ratio"), comp_catalog, warnings, f"buffer.{buffer_id}"
    )
    placement = buffer.get("placement") or {}
    llc_on = enabled(placement.get("llc_allocated", False))
    raw_weight = placement.get("llc_weight")
    llc_weight = float(raw_weight) if llc_on and raw_weight is not None else 1.0
    if not math.isfinite(llc_weight) or not 0 < llc_weight <= 1:
        raise ValueError(f"buffer.{buffer_id}: llc_weight must be finite and in (0, 1]")
    fmt = buffer.get("format")
    if warnings is not None and names and buffer.get("bitrate_mbps") is None and format_bpp_factor(fmt)[1] == "default":
        message = (f"{buffer_id}: format {fmt!r} has no bytes-per-pixel entry; counted as "
                   f"{BPP_DEFAULT:g} x bitdepth / 8 bytes per pixel.")
        if message not in warnings:
            warnings.append(message)
    # A planar YUV444 buffer has three full-size single-component planes.
    # Names remain physical driver DMA identifiers while BW counts each plane once.
    if len(names) == 3 and str(fmt).upper() == "YUV444":
        fmt = "Y"
    return [PortTransferSpec(
        node_id=workload.node_id, ip_ref=workload.ip_ref, hw_name=workload.hw_name,
        port=name, port_type=direction, width=width, height=height,
        format=fmt, bitwidth=int(buffer.get("bitdepth") or 8),
        compression=compression, comp_ratio=comp_ratio,
        llc_enabled=llc_on, llc_weight=llc_weight, r_w_rate=rate,
    ) for name in names]


DMA_ONLY = "dma_only"   # IPWorkload.mode of a SW-timed stand-in (fps 0 = the run rate)


def _node_surface(graph: CanonicalScenarioGraph, node_id: str) -> tuple[int, int] | None:
    """The surface a node declares in its variant sim block: width/height, else a 2-int ``dst`` (scaler output)."""
    sim = ((graph.variant.node_configs or {}).get(node_id) or {}).get("sim") or {}
    if not isinstance(sim, dict):
        return None
    w, h = sim.get("width"), sim.get("height")
    if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
        return w, h
    dst = sim.get("dst")
    if isinstance(dst, list) and len(dst) == 2 and all(isinstance(v, int) and v > 0 for v in dst):
        return dst[0], dst[1]
    return None


def _bitstream_transfers(graph: CanonicalScenarioGraph, workload: IPWorkload, buffer_id: str, buffer: dict[str, Any],
                         names: list[str], direction: PortType, rate: float,
                         warnings: list[str] | None) -> list[PortTransferSpec]:
    """A SW-timed node's side of a compressed stream: its bitrate (buffer, node sim, design condition), not a
    pixel surface; without one the transfer is left out and reported."""
    sim = ((graph.variant.node_configs or {}).get(workload.node_id) or {}).get("sim") or {}
    design = graph.variant.design_conditions or {}
    for raw in (buffer.get("bitrate_mbps"), sim.get("bitrate_mbps") if isinstance(sim, dict) else None,
                design.get("bitrate_mbps")):
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(raw) and raw > 0:
            return [PortTransferSpec(
                node_id=workload.node_id, ip_ref=workload.ip_ref, hw_name=workload.hw_name, port=name,
                port_type=direction, bitrate_mbps=float(raw), width=0, height=0, format="BITSTREAM",
                r_w_rate=rate) for name in names]
    if warnings is not None and names:
        message = f"{buffer_id}: {workload.node_id} bitstream has no bitrate_mbps; its DMA is excluded."
        if message not in warnings:
            warnings.append(message)
    return []


def sw_timed_dma_nodes(graph: CanonicalScenarioGraph, workloads: dict[str, IPWorkload]) -> dict[str, IPWorkload]:
    """IP nodes timed by ``sw_timing`` (GPU fallback composition, SW demux / DRM / decoder): not pixel workloads,
    but their M2M buffers still reach DRAM. A DMA-only stand-in (no clock, no power) per node, so
    ``edge_port_transfers`` counts the write / read on their side of the buffer (R-5b F-3)."""
    from scenario_db.sim.workloads import fallback_hw_name, is_external_non_compute_node

    out: dict[str, IPWorkload] = {}
    configs = graph.variant.node_configs or {}
    for node in graph.pipeline_nodes:
        node_id, ip_ref = str(node.get("id") or ""), node.get("ip_ref")
        if not node_id or not ip_ref or node_id in workloads or not (configs.get(node_id) or {}).get("sw_timing"):
            continue
        ip_row = graph.ip_catalog.get(str(ip_ref))
        if ip_row is None or is_external_non_compute_node(node, ip_row):
            continue
        hw_name = fallback_hw_name(str(ip_ref))
        sim = (configs.get(node_id) or {}).get("sim") or {}
        fps = sim.get("fps") if isinstance(sim, dict) else None
        own = float(fps) if isinstance(fps, (int, float)) and not isinstance(fps, bool) and fps > 0 else 0.0
        out[node_id] = IPWorkload(node_id=node_id, ip_ref=str(ip_ref), hw_name=hw_name, mode=DMA_ONLY, fps=own,
                                  sim_params=IPSimParams(hw_name=hw_name))
    return out


def dma_buffer_ids(graph: CanonicalScenarioGraph, workloads: dict[str, IPWorkload]) -> set[str]:
    """Buffers whose placement / compression reaches DRAM traffic: the buffer-derived DMA of
    ``edge_port_transfers`` (endpoints without explicit sim ports), history and standalone DMA."""
    from scenario_db.sim.workloads import node_sim_block
    explicit = {n for n in workloads if any((node_sim_block(graph, n) or {}).get(k) for k in ("inputs", "outputs"))}
    workloads = {**workloads, **sw_timed_dma_nodes(graph, workloads)}
    out = set()
    for edge in graph.pipeline_edges:
        bid = str(edge.get("buffer") or "")
        if bid and edge_type(edge) == "M2M" and any(
                str(n or "") in workloads and str(n or "") not in explicit for n in (edge_source(edge), edge_target(edge))):
            out.add(bid)
    for bid in (cast(dict[str, Any], graph.scenario.pipeline or {}).get("buffers") or {}):
        b = _effective_buffer(graph, bid)
        if str((b.get("history") or {}).get("node_id") or "") in workloads:
            out.add(bid)
        dma = b.get("dma") or {}
        node_id = str(dma.get("node_id") or "")
        flag = dma.get("activation_flag")
        if node_id in workloads and enabled(dma.get("enabled", True)) and (
                not flag or enabled(((graph.variant.node_configs or {}).get(node_id) or {}).get(flag, False))):
            out.add(bid)
    return out


def edge_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
    *,
    comp_catalog: dict[str, float] | None = None,
    warnings: list[str] | None = None,
    run_fps: float | None = None,
) -> list[PortTransferSpec]:
    specs: list[PortTransferSpec] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in graph.pipeline_edges:
        if edge_type(edge) != "M2M":
            continue
        source, target = str(edge_source(edge) or ""), str(edge_target(edge) or "")
        buffer_id = str(edge.get("buffer") or "")
        pairs = edge.get("port_pairs") or []
        surface = _node_surface(graph, source)
        for node_id, direction, key, fallback in (
            (source, PortType.DMA_WRITE, "src", f"{buffer_id or target}_WDMA"),
            (target, PortType.DMA_READ, "dst", f"{buffer_id or source}_RDMA"),
        ):
            if node_id not in workloads:
                continue
            names = list(dict.fromkeys(str(pair[key]) for pair in pairs if pair.get(key))) or [fallback]
            node = workloads[node_id]
            # a SW-timed stand-in moves the buffer at its own declared rate (sim.fps), not the run rate
            rate = node.fps / run_fps if getattr(node, "mode", None) == DMA_ONLY and node.fps > 0 and run_fps else 1.0
            for spec in _buffer_transfers(graph, node, buffer_id, names, direction, comp_catalog, warnings,
                                          rate=rate, fallback_size=surface):
                identity = (node_id, spec.port, buffer_id, direction)
                # Fan-out from the same MCSC buffer writes once, reads once per consumer.
                if identity not in seen:
                    seen.add(identity)
                    specs.append(spec)
    return specs


def history_rate(history: dict[str, Any], buffer_id: str = "history") -> float:
    """Average fraction of frames that move the previous-frame buffer.

    ``update_interval: N`` = the history DMA (read + write) runs once every N frames (e.g. a 30 fps
    temporal filter refreshing its reference at 15 fps -> N=2 -> 0.5). Absent = every frame.
    """
    raw = history.get("update_interval")
    if raw is None:
        return 1.0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 1:
        raise ValueError(f"{buffer_id}: history.update_interval must be a number >= 1")
    return 1.0 / float(raw)


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
        rate = history_rate(history, buffer_id)
        for key, direction in (("read_ports", PortType.DMA_READ), ("write_ports", PortType.DMA_WRITE)):
            specs.extend(_buffer_transfers(graph, workloads[node_id], buffer_id, history.get(key) or [], direction,
                                           comp_catalog, warnings, rate))
    return specs


def standalone_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
    comp_catalog: dict[str, float] | None = None,
    warnings: list[str] | None = None,
) -> list[PortTransferSpec]:
    """Declared auxiliary DMA with no modeled downstream consumer."""
    specs = []
    for buffer_id in (cast(dict[str, Any], graph.scenario.pipeline or {}).get("buffers") or {}):
        endpoint = _effective_buffer(graph, buffer_id).get("dma") or {}
        node_id = str(endpoint.get("node_id") or "")
        if node_id not in workloads or not enabled(endpoint.get("enabled", True)):
            continue
        flag = endpoint.get("activation_flag")
        config = (graph.variant.node_configs or {}).get(node_id) or {}
        if flag and not enabled(config.get(flag, False)):
            continue
        for key, direction in (("read_ports", PortType.DMA_READ), ("write_ports", PortType.DMA_WRITE)):
            specs.extend(_buffer_transfers(graph, workloads[node_id], buffer_id, endpoint.get(key) or [], direction, comp_catalog, warnings))
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
