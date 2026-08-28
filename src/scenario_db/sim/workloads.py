from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.graph_edges import edge_source, edge_target
from scenario_db.sim.models import IPSimParams, IPWorkload, SimulationRunConfig
from scenario_db.sim.shape_propagation import NodeShape


def build_workload_for_node(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    *,
    fps: float,
    run_config: SimulationRunConfig,
    warnings: list[str],
    shape: NodeShape | None = None,
) -> IPWorkload | None:
    node_id = str(node.get("id") or "")
    ip_ref = node.get("ip_ref")
    if not node_id or not ip_ref:
        return None
    ip_row = graph.ip_catalog.get(str(ip_ref))
    if ip_row is None or is_external_non_compute_node(node, ip_row):
        return None

    node_config = (graph.variant.node_configs or {}).get(node_id) or {}
    sim_block = node_config.get("sim") or {}
    mode = str(sim_block.get("mode") or node_config.get("selected_mode") or "Normal")
    role = str(node.get("role") or node_id)
    sim_params = sim_params_for_node(
        ip_row,
        sim_block,
        mode=mode,
        node_id=node_id,
        role=role,
        warnings=warnings,
    )
    width, height = workload_size(graph, node_id, sim_block, shape=shape)
    workload_format = workload_format_for_node(graph, node_id, sim_block, shape=shape)
    return IPWorkload(
        node_id=node_id,
        ip_ref=str(ip_ref),
        hw_name=sim_params.hw_name,
        mode=mode,
        width=width,
        height=height,
        format=workload_format,
        fps=float(sim_block.get("fps") or fps),
        sw_margin=float(sim_block.get("sw_margin") or run_config.sw_margin),
        manual_clock_mhz=sim_block.get("manual_clock_mhz"),
        sim_params=sim_params,
    )


def node_sim_block(graph: CanonicalScenarioGraph, node_id: str) -> dict[str, Any]:
    node_config = (graph.variant.node_configs or {}).get(node_id) or {}
    sim_block = node_config.get("sim") or {}
    return sim_block if isinstance(sim_block, dict) else {}


def is_external_non_compute_node(node: dict[str, Any], ip_row: Any) -> bool:
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


def sim_params_for_node(
    ip_row: Any,
    sim_block: dict[str, Any],
    *,
    mode: str,
    node_id: str,
    role: str,
    warnings: list[str],
) -> IPSimParams:
    capabilities = ip_row.capabilities or {}
    sim = capabilities.get("sim") or (capabilities.get("properties") or {}).get("sim") or {}
    if not isinstance(sim, dict):
        sim = {}
    mode_params = mode_sim_params(sim, mode)
    role_params = role_sim_params(sim, role)
    role_mode_params = mode_sim_params(role_params, mode)
    override_params = sim_block.get("ip_params") or {}
    if not isinstance(override_params, dict):
        override_params = {}
    override_mode_params = mode_sim_params(override_params, mode)
    if not sim and not override_params:
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has no capabilities.sim or sim.ip_params; "
            "ppc, unit power, DVFS group, and timing defaults will be zero."
        )
    elif declares_modes(sim, role_params, override_params) and not any(
        has_sim_values(params)
        for params in (sim, mode_params, role_params, role_mode_params, override_params, override_mode_params)
    ):
        warnings.append(
            f"{node_id} ({ip_row.id}, mode={mode}) has no matching sim mode; "
            "mode-specific ppc and unit power may default to zero."
        )
    merged = {**sim, **mode_params, **role_params, **role_mode_params, **override_params, **override_mode_params}
    hw_name = merged.get("hw_name") or merged.get("hw_name_in_sim") or fallback_hw_name(ip_row.id)
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
        source=merged.get("source") or sim.get("source"),
        source_project=merged.get("source_project") or sim.get("source_project"),
        source_note=merged.get("source_note") or sim.get("source_note"),
        mapping_source=_mapping_source(sim_block),
    )


def mode_sim_params(sim: dict[str, Any], mode: str) -> dict[str, Any]:
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


def declares_modes(*blocks: dict[str, Any]) -> bool:
    return any(isinstance(block.get("modes"), dict) and bool(block.get("modes")) for block in blocks)


def has_sim_values(block: dict[str, Any]) -> bool:
    return any(
        key in block and block.get(key) not in (None, "")
        for key in ("ppc", "unit_power_mw_mp", "vdd", "dvfs_group", "max_clock_mhz")
    )


def role_sim_params(sim: dict[str, Any], role: str) -> dict[str, Any]:
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


def workload_size(
    graph: CanonicalScenarioGraph,
    node_id: str,
    sim_block: dict[str, Any],
    *,
    shape: NodeShape | None = None,
) -> tuple[int, int]:
    if sim_block.get("width") and sim_block.get("height"):
        return int(sim_block["width"]), int(sim_block["height"])
    for key in ("inputs", "outputs"):
        for port in sim_block.get(key) or []:
            width, height = port_size(port)
            if width > 0 and height > 0:
                return width, height
    if _use_propagated_shape(sim_block) and shape is not None:
        for candidate in (shape.output, shape.input):
            if candidate.width > 0 and candidate.height > 0:
                return candidate.width, candidate.height

    candidates: list[tuple[int, int]] = []
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    for edge in graph.pipeline_edges:
        if node_id not in {edge_source(edge), edge_target(edge)}:
            continue
        buffer_ref = edge.get("buffer")
        if buffer_ref and buffer_ref in buffers:
            candidates.append(buffer_size(graph, buffers[buffer_ref]))
    candidates = [item for item in candidates if item[0] and item[1]]
    if candidates:
        return max(candidates, key=lambda item: item[0] * item[1])
    design_size = design_size_for_graph(graph)
    if design_size != (0, 0):
        return design_size
    return 0, 0


def workload_format_for_node(
    graph: CanonicalScenarioGraph,
    node_id: str,
    sim_block: dict[str, Any],
    *,
    shape: NodeShape | None = None,
) -> str | None:
    if sim_block.get("format"):
        return str(sim_block["format"])
    for key in ("inputs", "outputs"):
        for port in sim_block.get(key) or []:
            if port.get("format"):
                return str(port["format"])
    if _use_propagated_shape(sim_block) and shape is not None:
        if shape.output.format:
            return str(shape.output.format)
        if shape.input.format:
            return str(shape.input.format)
    buffers = (graph.scenario.pipeline or {}).get("buffers") or {}
    for edge in graph.pipeline_edges:
        if node_id not in {edge_source(edge), edge_target(edge)}:
            continue
        buffer_ref = edge.get("buffer")
        buffer = buffers.get(buffer_ref) if buffer_ref else None
        if isinstance(buffer, dict) and buffer.get("format"):
            return str(buffer["format"])
    design = graph.variant.design_conditions or {}
    fmt = design.get("format") or design.get("pixel_format")
    return str(fmt) if fmt else None


def port_size(port: dict[str, Any]) -> tuple[int, int]:
    if port.get("width") is not None and port.get("height") is not None:
        return int(port["width"]), int(port["height"])
    size = port.get("size") or []
    if isinstance(size, list) and len(size) >= 4:
        return int(size[2] or 0), int(size[3] or 0)
    return 0, 0


def buffer_size(graph: CanonicalScenarioGraph, buffer: dict[str, Any]) -> tuple[int, int]:
    size_ref = buffer.get("size_ref")
    size = None
    if size_ref:
        overrides = graph.variant.size_overrides or {}
        anchors = (graph.scenario.size_profile or {}).get("anchors") or {}
        size = overrides.get(size_ref) or anchors.get(size_ref)
    if isinstance(size, str) and "x" in size.lower():
        left, right = size.lower().split("x", 1)
        return int(left), int(right)
    return 0, 0


def design_size_for_graph(graph: CanonicalScenarioGraph) -> tuple[int, int]:
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


def fallback_hw_name(ip_ref: str) -> str:
    parts = str(ip_ref).split("-")
    if len(parts) >= 2 and parts[0] == "ip":
        return parts[1].upper()
    return str(ip_ref).upper()


def _use_propagated_shape(sim_block: dict[str, Any]) -> bool:
    return bool(sim_block.get("inherit_shape") or sim_block.get("shape_propagation"))


def _mapping_source(sim_block: dict[str, Any]) -> dict[str, Any]:
    mapping = sim_block.get("mapping_source") or sim_block.get("provenance") or {}
    return mapping if isinstance(mapping, dict) else {}
