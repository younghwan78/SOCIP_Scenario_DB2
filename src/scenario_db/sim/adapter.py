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
        workloads.append(
            IPWorkload(
                node_id=node_id,
                ip_ref=str(ip_ref),
                hw_name=sim_params.hw_name,
                mode=mode,
                width=width,
                height=height,
                fps=fps,
                sw_margin=float(sim_block.get("sw_margin") or run_config.sw_margin),
                manual_clock_mhz=sim_block.get("manual_clock_mhz"),
                sim_params=sim_params,
            )
        )
        transfers.extend(_port_transfers(node_id, str(ip_ref), sim_params.hw_name, sim_block))

    if not transfers:
        transfers.extend(_edge_port_transfers(graph, {item.node_id: item for item in workloads}))

    return SimulationInputs(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        project_ref=getattr(graph.scenario, "project_ref", None),
        config=run_config.model_copy(update={"fps": fps}),
        workloads=workloads,
        port_transfers=transfers,
        timeline_tasks=_timeline_tasks(graph),
        timeline_edges=_timeline_edges(graph),
        warnings=warnings,
    )


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
    sensor_mode = _selected_sensor_mode(graph)
    panel = _selected_panel_properties(graph)
    node_by_id = {str(node.get("id")): node for node in source_nodes if node.get("id")}
    result: list[dict[str, Any]] = []
    for task in tasks:
        updated = dict(task)
        node = node_by_id.get(str(task.get("id"))) or {}
        if sensor_mode and _is_sensor_timeline_task(task, node):
            _apply_sensor_constraint(updated, sensor_mode)
        if panel and _is_display_sink_task(task, node):
            _apply_panel_constraint(updated, panel, graph)
        result.append(updated)
    return result


def _selected_sensor_mode(graph: CanonicalScenarioGraph) -> dict[str, Any] | None:
    candidates = [
        row
        for row in graph.ip_catalog.values()
        if str(getattr(row, "category", "") or "").lower() == "sensor"
    ]
    if not candidates:
        return None
    design = graph.variant.design_conditions or {}
    selected_mode = design.get("sensor_mode") or design.get("sensor_mode_ref") or design.get("sensor")
    for row in candidates:
        properties = _capability_properties(row)
        modes = properties.get("modes") if isinstance(properties.get("modes"), dict) else {}
        if selected_mode and selected_mode in modes:
            return dict(modes[selected_mode])
        if modes:
            preferred = _mode_by_fps(modes, _variant_fps(graph))
            return dict(preferred or next(iter(modes.values())))
    return None


def _selected_panel_properties(graph: CanonicalScenarioGraph) -> dict[str, Any] | None:
    for row in graph.ip_catalog.values():
        category = str(getattr(row, "category", "") or "").lower()
        properties = _capability_properties(row)
        if "refresh_rates" in properties or "refresh_rate" in properties or "panel" in str(getattr(row, "id", "")).lower():
            if category in {"display", "panel"}:
                return dict(properties)
    return None


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
    size = mode.get("sensor_size")
    pclk = _float_or_none(mode.get("sensor_pclk"))
    line_length = _float_or_none(mode.get("sensor_line_length_pck"))
    if not isinstance(size, list) or len(size) < 2 or not pclk or not line_length:
        return None
    height = _float_or_none(size[1])
    if not height:
        return None
    return round(line_length * 1000.0 / pclk * height, 6)


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
