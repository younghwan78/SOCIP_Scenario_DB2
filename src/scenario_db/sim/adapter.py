from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.models import (
    IPSimParams,
    IPWorkload,
    PortTransferSpec,
    PortType,
    SimulationInputs,
    SimulationRunConfig,
)


def build_simulation_inputs(
    graph: CanonicalScenarioGraph,
    config: SimulationRunConfig | None = None,
) -> SimulationInputs:
    """Convert an effective canonical graph into simulation-engine inputs."""

    run_config = config or SimulationRunConfig()
    fps = _fps(graph, run_config)
    workloads: list[IPWorkload] = []
    transfers: list[PortTransferSpec] = []
    warnings: list[str] = []

    for node in graph.pipeline_nodes:
        node_id = str(node.get("id") or "")
        ip_ref = node.get("ip_ref")
        if not node_id or not ip_ref:
            continue
        ip_row = graph.ip_catalog.get(str(ip_ref))
        if ip_row is None:
            continue
        if _is_external_non_compute_node(node, ip_row):
            continue
        node_config = (graph.variant.node_configs or {}).get(node_id) or {}
        sim_block = node_config.get("sim") or {}
        mode = str(sim_block.get("mode") or node_config.get("selected_mode") or "Normal")
        role = str(node.get("role") or node_id)
        sim_params = _sim_params(
            ip_row,
            sim_block,
            mode=mode,
            node_id=node_id,
            role=role,
            warnings=warnings,
        )
        width, height = _workload_size(graph, node_id, sim_block)
        workload_format = _workload_format(graph, node_id, sim_block)
        workloads.append(
            IPWorkload(
                node_id=node_id,
                ip_ref=str(ip_ref),
                hw_name=sim_params.hw_name,
                mode=mode,
                width=width,
                height=height,
                format=workload_format,
                fps=fps,
                sw_margin=float(sim_block.get("sw_margin") or run_config.sw_margin),
                manual_clock_mhz=sim_block.get("manual_clock_mhz"),
                sim_params=sim_params,
            )
        )
        transfers.extend(_port_transfers(node_id, str(ip_ref), sim_params.hw_name, sim_block))

    if not transfers:
        transfers.extend(_edge_port_transfers(graph, {item.node_id: item for item in workloads}))

    _apply_sensor_otf_clock_corrections(graph, workloads, warnings)

    return SimulationInputs(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        project_ref=getattr(graph.scenario, "project_ref", None),
        config=run_config.model_copy(update={"fps": fps}),
        workloads=workloads,
        port_transfers=transfers,
        timeline_tasks=_timeline_tasks(graph),
        timeline_edges=_timeline_edges(graph),
        external_devices=_external_devices(graph),
        topology_order=[item.node_id for item in workloads],
        warnings=warnings,
    )


def _apply_sensor_otf_clock_corrections(
    graph: CanonicalScenarioGraph,
    workloads: list[IPWorkload],
    warnings: list[str],
) -> None:
    workload_by_node = {item.node_id: item for item in workloads}
    for sensor_node in _active_sensor_nodes(graph):
        sensor_mode = _selected_sensor_mode(graph, sensor_node)
        if not sensor_mode:
            continue
        sensor_node_id = str(sensor_node.get("id") or "")
        mipi_speed = _float_or_none(sensor_mode.get("sensor_mipi_speed"))
        bitwidth = _float_or_none(sensor_mode.get("sensor_bitwidth"))
        phy_type = str(sensor_mode.get("sensor_phy_type") or "DPHY").upper()
        v_valid_ms = _float_or_none(sensor_mode.get("v_valid_ms")) or _calc_v_valid_ms(sensor_mode)
        if not mipi_speed or not bitwidth:
            warnings.append(
                f"{sensor_node.get('id')} has no sensor_mipi_speed/sensor_bitwidth; "
                "sensor ingress MIPI clock correction is not applied."
            )
        else:
            for node_id in _sensor_direct_otf_target_node_ids(graph, sensor_node_id):
                workload = workload_by_node.get(node_id)
                if workload is None or workload.sim_params.ppc <= 0:
                    continue
                req_clock = _req_csis_clock_mhz(
                    sensor_mipi_speed=mipi_speed,
                    sensor_bitwidth=bitwidth,
                    sensor_phy_type=phy_type,
                    ppc=workload.sim_params.ppc,
                )
                _raise_clock_correction(
                    workload,
                    req_clock,
                    reason=(
                        f"sensor_ingress_req_csis_clock({sensor_node.get('id')}, "
                        f"phy={phy_type}, mipi={mipi_speed:g}Gbps, bitwidth={bitwidth:g})"
                    ),
                )

        for node_id in _sensor_otf_connected_node_ids(graph, sensor_node_id):
            workload = workload_by_node.get(node_id)
            if workload is None or workload.sim_params.ppc <= 0:
                continue
            stream_clock = _req_vvalid_stream_clock_mhz(workload, v_valid_ms)
            _raise_clock_correction(
                workload,
                stream_clock,
                reason=f"sensor_vvalid_stream_clock({sensor_node.get('id')}, v_valid_ms={v_valid_ms})",
            )

    _apply_otf_group_clock_alignment(graph, workloads)


def _raise_clock_correction(workload: IPWorkload, clock_mhz: float, *, reason: str) -> None:
    if clock_mhz > workload.clock_correction_mhz:
        workload.clock_correction_mhz = clock_mhz
        workload.clock_correction_reason = reason


def _apply_otf_group_clock_alignment(
    graph: CanonicalScenarioGraph,
    workloads: list[IPWorkload],
) -> None:
    workload_by_node = {item.node_id: item for item in workloads}
    for group_index, group in enumerate(_otf_node_groups(graph)):
        group_workloads = [workload_by_node[node_id] for node_id in group if node_id in workload_by_node]
        if len(group_workloads) < 2:
            continue
        required_by_node = {
            workload.node_id: _pre_resolver_required_clock_mhz(workload)
            for workload in group_workloads
        }
        leader_node_id, group_clock = max(
            required_by_node.items(),
            key=lambda item: (item[1], item[0]),
        )
        if group_clock <= 0:
            continue
        for workload in group_workloads:
            _raise_clock_correction(
                workload,
                group_clock,
                reason=f"otf_group_clock_align(otf-{group_index}, leader={leader_node_id})",
            )


def _pre_resolver_required_clock_mhz(workload: IPWorkload) -> float:
    required = _base_required_clock_mhz(workload)
    if workload.manual_clock_mhz and workload.manual_clock_mhz > required:
        required = workload.manual_clock_mhz
    if workload.clock_correction_mhz > required:
        required = workload.clock_correction_mhz
    return required


def _base_required_clock_mhz(workload: IPWorkload) -> float:
    params = workload.sim_params
    if workload.pixels <= 0 or workload.fps <= 0 or params.ppc <= 0:
        return 0.0
    usable = max(1e-9, 1.0 - workload.sw_margin)
    return workload.pixels * workload.fps / usable / params.ppc / 1e6


def _req_vvalid_stream_clock_mhz(workload: IPWorkload, v_valid_ms: float | None) -> float:
    params = workload.sim_params
    if workload.pixels <= 0 or not v_valid_ms or v_valid_ms <= 0 or params.ppc <= 0:
        return 0.0
    return workload.pixels / v_valid_ms / params.ppc / 1000.0


def _fps(graph: CanonicalScenarioGraph, config: SimulationRunConfig) -> float:
    if config.fps is not None:
        return float(config.fps)
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or 30.0)


def _is_external_non_compute_node(node: dict[str, Any], ip_row: Any) -> bool:
    """Return true for external source/sink parts that should not be DVFS workloads."""

    category = str(getattr(ip_row, "category", "") or "").lower()
    text = " ".join(
        str(value or "").lower()
        for value in (
            node.get("id"),
            node.get("role"),
            node.get("node_type"),
            node.get("label"),
            getattr(ip_row, "id", ""),
        )
    )
    if category == "sensor" or "sensor" in text:
        return True
    if category == "panel" or "panel" in text:
        return True
    if category == "memory" or "llc" in text:
        return True
    return False


def _sim_params(
    ip_row: Any,
    sim_block: dict[str, Any],
    *,
    mode: str,
    node_id: str,
    role: str,
    warnings: list[str],
) -> IPSimParams:
    capabilities = ip_row.capabilities or {}
    sim = (
        capabilities.get("sim")
        or (capabilities.get("properties") or {}).get("sim")
        or {}
    )
    if not isinstance(sim, dict):
        sim = {}
    mode_params = _mode_sim_params(sim, mode)
    role_params = _role_sim_params(sim, role)
    role_mode_params = _mode_sim_params(role_params, mode)
    override_params = sim_block.get("ip_params") or {}
    if not isinstance(override_params, dict):
        override_params = {}
    override_mode_params = _mode_sim_params(override_params, mode)
    if not sim and not override_params:
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has no capabilities.sim or sim.ip_params; "
            "ppc, unit power, DVFS group, and timing defaults will be zero."
        )
    elif _declares_modes(sim, role_params, override_params) and not any(
        _has_sim_values(params)
        for params in (sim, mode_params, role_params, role_mode_params, override_params, override_mode_params)
    ):
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has no matching sim mode; "
            "mode-specific ppc and unit power may default to zero."
        )
    merged = {**sim, **mode_params, **role_params, **role_mode_params, **override_params, **override_mode_params}
    hw_name = merged.get("hw_name") or merged.get("hw_name_in_sim") or _fallback_hw_name(ip_row.id)
    ppc = float(merged.get("ppc") or 0.0)
    unit_power = float(merged.get("unit_power_mw_mp") or 0.0)
    if ppc <= 0:
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has ppc=0; "
            "clock and timing estimates may be zero."
        )
    if unit_power <= 0:
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has unit_power_mw_mp=0.0; "
            "core power estimate will be zero."
        )
    return IPSimParams(
        hw_name=str(hw_name),
        ppc=ppc,
        unit_power_mw_mp=unit_power,
        idc=float(merged.get("idc") or 0.0),
        vdd=merged.get("vdd"),
        dvfs_group=merged.get("dvfs_group"),
        max_clock_mhz=merged.get("max_clock_mhz"),
    )


def _mode_sim_params(sim: dict[str, Any], mode: str) -> dict[str, Any]:
    modes = sim.get("modes") or {}
    if not isinstance(modes, dict):
        return {}
    if mode in modes:
        return modes[mode]
    mode_text = str(mode)
    if mode_text in modes:
        return modes[mode_text]
    for key, value in modes.items():
        if str(key).lower() == mode_text.lower() and isinstance(value, dict):
            return value
    return {}


def _declares_modes(*blocks: dict[str, Any]) -> bool:
    return any(isinstance(block.get("modes"), dict) and bool(block.get("modes")) for block in blocks)


def _has_sim_values(block: dict[str, Any]) -> bool:
    return any(
        key in block and block.get(key) not in (None, "")
        for key in ("ppc", "unit_power_mw_mp", "vdd", "dvfs_group", "max_clock_mhz")
    )


def _role_sim_params(sim: dict[str, Any], role: str) -> dict[str, Any]:
    role_modes = sim.get("role_modes") or {}
    if not isinstance(role_modes, dict):
        return {}
    candidates = [
        role,
        role.lower(),
        role.upper(),
        role.replace("_", "-").lower(),
        role.replace("-", "_").lower(),
    ]
    for candidate in candidates:
        params = role_modes.get(candidate)
        if isinstance(params, dict):
            return params
    return {}


def _workload_size(
    graph: CanonicalScenarioGraph,
    node_id: str,
    sim_block: dict[str, Any],
) -> tuple[int, int]:
    if sim_block.get("width") and sim_block.get("height"):
        return int(sim_block["width"]), int(sim_block["height"])
    for key in ("inputs", "outputs"):
        for port in sim_block.get(key) or []:
            width, height = _port_size(port)
            if width > 0 and height > 0:
                return width, height

    # Last resort: use the largest buffer touching the node.
    candidates: list[tuple[int, int]] = []
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    for edge in graph.pipeline_edges:
        if node_id not in {_edge_source(edge), _edge_target(edge)}:
            continue
        buffer_ref = edge.get("buffer")
        if buffer_ref and buffer_ref in buffers:
            candidates.append(_buffer_size(graph, buffers[buffer_ref]))
    candidates = [item for item in candidates if item[0] and item[1]]
    if candidates:
        return max(candidates, key=lambda item: item[0] * item[1])
    design_size = _design_size(graph)
    if design_size != (0, 0):
        return design_size
    return 0, 0


def _workload_format(
    graph: CanonicalScenarioGraph,
    node_id: str,
    sim_block: dict[str, Any],
) -> str | None:
    if sim_block.get("format"):
        return str(sim_block["format"])
    for key in ("inputs", "outputs"):
        for port in sim_block.get(key) or []:
            if port.get("format"):
                return str(port["format"])
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    for edge in graph.pipeline_edges:
        if node_id not in {_edge_source(edge), _edge_target(edge)}:
            continue
        buffer_ref = edge.get("buffer")
        buffer = buffers.get(buffer_ref) if buffer_ref else None
        if isinstance(buffer, dict) and buffer.get("format"):
            return str(buffer["format"])
    design = graph.variant.design_conditions or {}
    fmt = design.get("format") or design.get("pixel_format")
    return str(fmt) if fmt else None


def _edge_port_transfers(
    graph: CanonicalScenarioGraph,
    workloads: dict[str, IPWorkload],
) -> list[PortTransferSpec]:
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    specs: list[PortTransferSpec] = []
    for edge in graph.pipeline_edges:
        if str(edge.get("type") or "").upper() != "M2M":
            continue
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        buffer = buffers.get(edge.get("buffer")) if edge.get("buffer") else {}
        width, height = _buffer_size(graph, buffer) if isinstance(buffer, dict) else (0, 0)
        if width == 0 or height == 0:
            width, height = _design_size(graph)
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


def _port_transfers(
    node_id: str,
    ip_ref: str,
    hw_name: str,
    sim_block: dict[str, Any],
) -> list[PortTransferSpec]:
    specs: list[PortTransferSpec] = []
    for key, default_type in (("inputs", PortType.DMA_READ), ("outputs", PortType.DMA_WRITE)):
        for port in sim_block.get(key) or []:
            width, height = _port_size(port)
            port_type = _port_type(port, default_type)
            specs.append(
                PortTransferSpec(
                    node_id=node_id,
                    ip_ref=ip_ref,
                    hw_name=hw_name,
                    port=str(port.get("port") or port.get("name") or key),
                    port_type=port_type,
                    width=width,
                    height=height,
                    format=port.get("format"),
                    bitwidth=int(port.get("bitwidth") or 8),
                    compression=str(port.get("compression") or port.get("comp") or "disable"),
                    comp_ratio=float(port.get("comp_ratio") or 1.0),
                    comp_ratio_min=port.get("comp_ratio_min"),
                    comp_ratio_max=port.get("comp_ratio_max"),
                    llc_enabled=_enabled(port.get("llc_enabled", port.get("llc_enable", False))),
                    llc_weight=float(port.get("llc_weight") or 1.0),
                    r_w_rate=float(port.get("r_w_rate") or 1.0),
                )
            )
    return specs


def _port_size(port: dict[str, Any]) -> tuple[int, int]:
    if port.get("width") is not None and port.get("height") is not None:
        return int(port["width"]), int(port["height"])
    size = port.get("size") or []
    if isinstance(size, list) and len(size) >= 4:
        return int(size[2] or 0), int(size[3] or 0)
    return 0, 0


def _port_type(port: dict[str, Any], default: PortType) -> PortType:
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


def _timeline_tasks(graph: CanonicalScenarioGraph) -> list[dict]:
    task_graph = (graph.scenario.pipeline or {}).get("task_graph") or {}
    nodes = task_graph.get("nodes") or []
    if nodes:
        tasks = [
            {
                "id": str(node.get("id")),
                "node_id": node.get("id"),
                "hw_name": _label_hw_name(node),
                "task_type": "sw" if str(node.get("layer") or "").lower() in {"app", "framework", "hal", "kernel"} else "hw",
                "duration_ms": node.get("duration_ms") or node.get("manual_hw_time_ms") or 0.0,
            }
            for node in nodes
            if node.get("id")
        ]
        return _apply_source_sink_constraints(graph, tasks, nodes)
    tasks = [
        {
            "id": str(node.get("id")),
            "node_id": node.get("id"),
            "hw_name": _fallback_hw_name(str(node.get("ip_ref") or node.get("id"))),
            "task_type": "hw",
            "duration_ms": 0.0,
        }
        for node in graph.pipeline_nodes
        if node.get("id")
    ]
    return _apply_source_sink_constraints(graph, tasks, graph.pipeline_nodes)


def _timeline_edges(graph: CanonicalScenarioGraph) -> list[dict]:
    task_graph = (graph.scenario.pipeline or {}).get("task_graph") or {}
    return list(task_graph.get("edges") or graph.pipeline_edges)


def _apply_source_sink_constraints(
    graph: CanonicalScenarioGraph,
    tasks: list[dict[str, Any]],
    source_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    panel = _selected_panel_properties(graph)
    node_by_id = {str(node.get("id")): node for node in source_nodes if node.get("id")}
    result: list[dict[str, Any]] = []
    for task in tasks:
        updated = dict(task)
        node = node_by_id.get(str(task.get("id"))) or {}
        sensor_mode = _selected_sensor_mode(graph, node)
        if sensor_mode and _is_sensor_timeline_task(task, node):
            _apply_sensor_constraint(updated, sensor_mode)
        if panel and _is_display_sink_task(task, node):
            _apply_panel_constraint(updated, panel, graph)
        result.append(updated)
    return result


def _external_devices(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for node in graph.pipeline_nodes:
        ip_ref = str(node.get("ip_ref") or "")
        ip_row = graph.ip_catalog.get(ip_ref)
        if ip_row is None:
            continue
        category = str(getattr(ip_row, "category", "") or "").lower()
        text = _task_node_text({}, node)
        properties = _capability_properties(ip_row)
        panel_like = (
            category == "panel"
            or "panel" in text
            or str(properties.get("role") or "").lower() == "panel"
        )
        if category == "sensor" or "sensor" in text:
            mode = _selected_sensor_mode(graph, node) or {}
            device = _sensor_device_info(graph, node, ip_row, mode)
            if device:
                devices.append(device)
        elif panel_like:
            panel = _selected_panel_properties(graph) or {}
            device = _display_device_info(graph, node, ip_row, panel)
            if device:
                devices.append(device)
    return devices


def _active_sensor_nodes(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in graph.pipeline_nodes:
        ip_ref = str(node.get("ip_ref") or "")
        ip_row = graph.ip_catalog.get(ip_ref)
        category = str(getattr(ip_row, "category", "") or "").lower() if ip_row is not None else ""
        if category == "sensor" or "sensor" in _task_node_text({}, node):
            result.append(node)
    return result


def _sensor_otf_connected_node_ids(graph: CanonicalScenarioGraph, sensor_node_id: str) -> set[str]:
    edges_by_source: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.pipeline_edges:
        edges_by_source.setdefault(str(_edge_source(edge) or ""), []).append(edge)
    visited: set[str] = set()
    connected: set[str] = set()
    queue = [sensor_node_id]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for edge in edges_by_source.get(current, []):
            if str(edge.get("type") or "").upper() != "OTF":
                continue
            target = str(_edge_target(edge) or "")
            if not target:
                continue
            if target != sensor_node_id:
                connected.add(target)
            queue.append(target)
    connected.discard(sensor_node_id)
    return connected


def _sensor_direct_otf_target_node_ids(graph: CanonicalScenarioGraph, sensor_node_id: str) -> set[str]:
    targets: set[str] = set()
    for edge in graph.pipeline_edges:
        if str(_edge_source(edge) or "") != sensor_node_id:
            continue
        if str(edge.get("type") or "").upper() != "OTF":
            continue
        target = str(_edge_target(edge) or "")
        if target:
            targets.add(target)
    return targets


def _otf_node_groups(graph: CanonicalScenarioGraph) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {}
    rank = {str(node.get("id") or ""): index for index, node in enumerate(graph.pipeline_nodes)}
    for edge in graph.pipeline_edges:
        if str(edge.get("type") or "").upper() != "OTF":
            continue
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, set()).add(target)
        adjacency.setdefault(target, set()).add(source)

    groups: list[list[str]] = []
    visited: set[str] = set()
    for node_id in sorted(adjacency, key=lambda item: rank.get(item, 10**9)):
        if node_id in visited:
            continue
        queue = [node_id]
        group: list[str] = []
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            group.append(current)
            queue.extend(sorted(adjacency.get(current, set()) - visited, key=lambda item: rank.get(item, 10**9)))
        groups.append(sorted(group, key=lambda item: rank.get(item, 10**9)))
    return groups


def _req_csis_clock_mhz(
    *,
    sensor_mipi_speed: float,
    sensor_bitwidth: float,
    sensor_phy_type: str,
    ppc: float,
) -> float:
    if sensor_mipi_speed <= 0 or sensor_bitwidth <= 0 or ppc <= 0:
        return 0.0
    if sensor_phy_type.upper() == "CPHY":
        return sensor_mipi_speed * (16.0 / 7.0) * 3.0 / (sensor_bitwidth * ppc) * 1000.0
    return sensor_mipi_speed * 4.0 / (sensor_bitwidth * ppc) * 1000.0


def _selected_sensor_mode(graph: CanonicalScenarioGraph, node: dict[str, Any] | None = None) -> dict[str, Any] | None:
    row = _selected_sensor_row(graph, node)
    if row is None:
        return None
    design = graph.variant.design_conditions or {}
    selected_mode = design.get("sensor_mode") or design.get("sensor_mode_ref") or design.get("sensor")
    properties = _capability_properties(row)
    modes = properties.get("modes") if isinstance(properties.get("modes"), dict) else {}
    if not modes:
        return None
    if selected_mode and selected_mode in modes and isinstance(modes[selected_mode], dict):
        return _annotated_sensor_mode(row, selected_mode, modes[selected_mode], graph)
    preferred = _preferred_sensor_mode(modes, graph)
    if preferred:
        mode_id, mode = preferred
        return _annotated_sensor_mode(row, mode_id, mode, graph)
    mode_id, mode = next((key, value) for key, value in modes.items() if isinstance(value, dict))
    return _annotated_sensor_mode(row, str(mode_id), mode, graph)


def _selected_sensor_row(graph: CanonicalScenarioGraph, node: dict[str, Any] | None = None) -> Any | None:
    candidates = [
        row
        for row in graph.ip_catalog.values()
        if str(getattr(row, "category", "") or "").lower() == "sensor"
    ]
    if not candidates:
        return None
    if node and node.get("ip_ref"):
        row = graph.ip_catalog.get(str(node.get("ip_ref")))
        if row is not None and str(getattr(row, "category", "") or "").lower() == "sensor":
            return row
    design = graph.variant.design_conditions or {}
    sensor_place = str(design.get("sensor_place") or design.get("sensor_places") or "").lower()
    if sensor_place:
        for row in candidates:
            properties = _capability_properties(row)
            place = str(properties.get("place") or "").lower()
            row_id = str(getattr(row, "id", "") or "").lower()
            if place and place in sensor_place:
                return row
            if place and place in row_id and place in sensor_place:
                return row
    return candidates[0]


def _preferred_sensor_mode(modes: dict[str, Any], graph: CanonicalScenarioGraph) -> tuple[str, dict[str, Any]] | None:
    fps = _variant_fps(graph)
    design = graph.variant.design_conditions or {}
    design_text = " ".join(str(value or "").lower() for value in design.values())
    video = "video" in design_text or "rec" in str(graph.scenario_id).lower()
    if video:
        video_modes = [
            (str(key), value)
            for key, value in modes.items()
            if isinstance(value, dict)
            and ("wide" in str(key).lower() or "video" in str(key).lower() or _is_16_9_size(value.get("sensor_size")))
        ]
        if video_modes:
            return min(
                video_modes,
                key=lambda item: abs((_float_or_none(item[1].get("sensor_fps")) or fps) - fps),
            )
    best = _mode_by_fps(modes, fps)
    if best:
        for key, value in modes.items():
            if value is best:
                return str(key), best
    return None


def _annotated_sensor_mode(row: Any, mode_id: str, mode: dict[str, Any], graph: CanonicalScenarioGraph) -> dict[str, Any]:
    properties = _capability_properties(row)
    result = dict(mode)
    result["mode_id"] = mode_id
    result["ip_ref"] = getattr(row, "id", None)
    result["place"] = properties.get("place")
    result["sensor_phy_type"] = result.get("sensor_phy_type") or properties.get("phy_type")
    active_size, source = _active_sensor_size(result, graph)
    if active_size:
        result["active_size"] = list(active_size)
        result["active_size_source"] = source
    return result


def _selected_panel_properties(graph: CanonicalScenarioGraph) -> dict[str, Any] | None:
    for row in graph.ip_catalog.values():
        category = str(getattr(row, "category", "") or "").lower()
        properties = _capability_properties(row)
        if "refresh_rates" in properties or "refresh_rate" in properties or "panel" in str(getattr(row, "id", "")).lower():
            if category in {"display", "panel"}:
                return dict(properties)
    return None


def _sensor_device_info(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    ip_row: Any,
    mode: dict[str, Any],
) -> dict[str, Any]:
    v_valid_ms = _float_or_none(mode.get("v_valid_ms")) or _calc_v_valid_ms(mode)
    active_size = mode.get("active_size")
    sensor_size = mode.get("sensor_size")
    size = active_size if isinstance(active_size, list) and len(active_size) >= 2 else sensor_size
    return {
        "device_type": "sensor",
        "node_id": node.get("id"),
        "ip_ref": getattr(ip_row, "id", None),
        "role": node.get("role"),
        "place": mode.get("place") or _capability_properties(ip_row).get("place"),
        "mode": mode.get("mode_id") or mode.get("sensor_mode") or mode.get("sensor_name"),
        "name": mode.get("sensor_name"),
        "size": _size_text(size),
        "catalog_size": _size_text(sensor_size),
        "active_size": _size_text(active_size),
        "active_size_source": mode.get("active_size_source"),
        "format": mode.get("sensor_format"),
        "bitwidth": mode.get("sensor_bitwidth"),
        "fps": mode.get("sensor_fps") or _variant_fps(graph),
        "v_valid_ms": v_valid_ms,
        "v_valid_source": _v_valid_source(mode),
        "pclk": mode.get("sensor_pclk"),
        "line_length_pck": mode.get("sensor_line_length_pck"),
        "phy_type": mode.get("sensor_phy_type"),
        "mipi_speed": mode.get("sensor_mipi_speed"),
        "sbwc": mode.get("sensor_sbwc"),
    }


def _display_device_info(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    ip_row: Any,
    panel: dict[str, Any],
) -> dict[str, Any]:
    refresh_hz = _selected_refresh_hz(panel, _variant_fps(graph))
    display_size = panel.get("display_size") or panel.get("layout_size")
    return {
        "device_type": "display",
        "node_id": node.get("id"),
        "ip_ref": getattr(ip_row, "id", None),
        "role": node.get("role"),
        "layout": panel.get("layout") or panel.get("panel_layout"),
        "size": _size_text(display_size),
        "format": panel.get("format") or panel.get("pixel_format"),
        "fps": _variant_fps(graph),
        "refresh_hz": refresh_hz,
        "scanout_ms": (1000.0 / refresh_hz) if refresh_hz and refresh_hz > 0 else None,
        "panel_type": panel.get("panel_type"),
        "ppi": panel.get("ppi"),
    }


def _active_sensor_size(mode: dict[str, Any], graph: CanonicalScenarioGraph) -> tuple[tuple[int, int] | None, str | None]:
    for key in ("active_size", "sensor_active_size", "video_size", "crop_size"):
        size = _size_tuple(mode.get(key))
        if size:
            return size, key
    catalog_size = _size_tuple(mode.get("sensor_size"))
    if not catalog_size:
        return None, None
    design = graph.variant.design_conditions or {}
    design_size = _design_size(graph)
    design_text = " ".join(str(value or "").lower() for value in design.values())
    video = "video" in design_text or "rec" in str(graph.scenario_id).lower()
    if video and design_size and _is_16_9_tuple(design_size) and not _is_16_9_tuple(catalog_size):
        width, height = catalog_size
        cropped_height = int(round(width * 9 / 16))
        if 0 < cropped_height <= height:
            return (width, _make_even(cropped_height)), "derived_16_9_crop_from_catalog_width"
        cropped_width = int(round(height * 16 / 9))
        if 0 < cropped_width <= width:
            return (_make_even(cropped_width), height), "derived_16_9_crop_from_catalog_height"
    return catalog_size, "catalog_sensor_size"


def _size_text(value: Any) -> str | None:
    size = _size_tuple(value)
    if not size:
        return None
    return f"{size[0]}x{size[1]}"


def _size_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str) and "x" in value.lower():
        left, right = value.lower().split("x", 1)
        try:
            return int(left), int(right)
        except ValueError:
            return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0] or 0), int(value[1] or 0)
        except (TypeError, ValueError):
            return None
    return None


def _is_16_9_size(value: Any) -> bool:
    size = _size_tuple(value)
    return bool(size and _is_16_9_tuple(size))


def _is_16_9_tuple(size: tuple[int, int]) -> bool:
    width, height = size
    return width > 0 and height > 0 and abs((width / height) - (16 / 9)) < 0.02


def _make_even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def _apply_sensor_constraint(task: dict[str, Any], sensor_mode: dict[str, Any]) -> None:
    sensor_fps = _float_or_none(sensor_mode.get("sensor_fps"))
    v_valid_ms = _float_or_none(sensor_mode.get("v_valid_ms")) or _calc_v_valid_ms(sensor_mode)
    task["constraint_type"] = "source"
    if sensor_fps and sensor_fps > 0:
        task["source_fps"] = sensor_fps
        task["release_period_ms"] = 1000.0 / sensor_fps
    if v_valid_ms and v_valid_ms > 0:
        task["v_valid_ms"] = v_valid_ms
        task["source_valid_ms"] = v_valid_ms
        if not float(task.get("duration_ms") or 0.0):
            task["duration_ms"] = v_valid_ms


def _apply_panel_constraint(task: dict[str, Any], panel: dict[str, Any], graph: CanonicalScenarioGraph) -> None:
    refresh_hz = _selected_refresh_hz(panel, _variant_fps(graph))
    if not refresh_hz or refresh_hz <= 0:
        return
    scanout_ms = 1000.0 / refresh_hz
    task["constraint_type"] = "sink"
    task["refresh_hz"] = refresh_hz
    task["scanout_ms"] = scanout_ms
    task["deadline_ms"] = scanout_ms


def _is_sensor_timeline_task(task: dict[str, Any], node: dict[str, Any]) -> bool:
    text = _task_node_text(task, node)
    return "sensor" in text


def _is_display_sink_task(task: dict[str, Any], node: dict[str, Any]) -> bool:
    text = _task_node_text(task, node)
    return "panel" in text or "dpu" in text or "display" in text


def _task_node_text(task: dict[str, Any], node: dict[str, Any]) -> str:
    return " ".join(
        str(value or "").lower()
        for value in (
            task.get("id"),
            task.get("node_id"),
            task.get("hw_name"),
            node.get("id"),
            node.get("role"),
            node.get("label"),
            node.get("ip_ref"),
        )
    )


def _capability_properties(ip_row: Any) -> dict[str, Any]:
    capabilities = ip_row.capabilities or {}
    properties = capabilities.get("properties") if isinstance(capabilities, dict) else None
    return properties if isinstance(properties, dict) else {}


def _mode_by_fps(modes: dict[str, Any], fps: float) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for mode in modes.values():
        if not isinstance(mode, dict):
            continue
        sensor_fps = _float_or_none(mode.get("sensor_fps"))
        if sensor_fps is None:
            continue
        score = abs(sensor_fps - fps)
        if best is None or score < best[0]:
            best = (score, mode)
    return best[1] if best else None


def _selected_refresh_hz(panel: dict[str, Any], fps: float) -> float | None:
    raw = panel.get("refresh_rates") or panel.get("refresh_rate")
    rates = raw if isinstance(raw, list) else [raw]
    values = sorted(value for value in (_float_or_none(item) for item in rates) if value and value > 0)
    if not values:
        return None
    for value in values:
        if value >= fps:
            return value
    return values[-1]


def _calc_v_valid_ms(mode: dict[str, Any]) -> float | None:
    size = mode.get("active_size") or mode.get("sensor_size")
    pclk = _float_or_none(mode.get("sensor_pclk"))
    line_length = _float_or_none(mode.get("sensor_line_length_pck"))
    height = _size_tuple(size)[1] if _size_tuple(size) else None
    if height and pclk and line_length:
        return round(line_length * 1000.0 / pclk * height, 6)
    sensor_fps = _float_or_none(mode.get("sensor_fps"))
    if sensor_fps and sensor_fps > 0:
        return round(1000.0 / sensor_fps, 6)
    return None


def _v_valid_source(mode: dict[str, Any]) -> str | None:
    if mode.get("v_valid_ms") is not None:
        return "explicit_v_valid_ms"
    if mode.get("sensor_pclk") and mode.get("sensor_line_length_pck"):
        return "sensor_line_length_pck * 1000 / sensor_pclk * height"
    if mode.get("sensor_fps"):
        return "frame_period_fallback_no_vblank"
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _variant_fps(graph: CanonicalScenarioGraph) -> float:
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or 30.0)


def _buffer_size(graph: CanonicalScenarioGraph, buffer: dict[str, Any]) -> tuple[int, int]:
    size_ref = buffer.get("size_ref")
    size = None
    if size_ref:
        overrides = graph.variant.size_overrides or {}
        anchors = ((graph.scenario.size_profile or {}).get("anchors") or {})
        size = overrides.get(size_ref) or anchors.get(size_ref)
    if isinstance(size, str) and "x" in size.lower():
        left, right = size.lower().split("x", 1)
        return int(left), int(right)
    return 0, 0


def _design_size(graph: CanonicalScenarioGraph) -> tuple[int, int]:
    design = graph.variant.design_conditions or {}
    for key in ("size", "resolution_size", "output_size"):
        value = design.get(key)
        if isinstance(value, str) and "x" in value.lower():
            left, right = value.lower().split("x", 1)
            return int(left), int(right)
    value = design.get("resolution")
    mapping = {
        "FHD": (1920, 1080),
        "QHD": (2560, 1440),
        "UHD": (3840, 2160),
        "4K": (3840, 2160),
        "8K": (7680, 4320),
    }
    return mapping.get(str(value).upper(), (0, 0))


def _fallback_hw_name(ip_ref: str) -> str:
    parts = str(ip_ref).split("-")
    if len(parts) >= 2 and parts[0] == "ip":
        return parts[1].upper()
    return str(ip_ref).upper()


def _label_hw_name(node: dict[str, Any]) -> str:
    if node.get("hw_name"):
        return str(node["hw_name"])
    if node.get("ip_ref"):
        return _fallback_hw_name(str(node["ip_ref"]))
    label = str(node.get("label") or node.get("id") or "")
    return label.splitlines()[0].strip() or str(node.get("id"))


def _enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"enable", "enabled", "true", "1", "yes"}


def _edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def _edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")
