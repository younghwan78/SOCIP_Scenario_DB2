from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.models import IPWorkload


def apply_sensor_otf_clock_corrections(
    graph: CanonicalScenarioGraph,
    workloads: list[IPWorkload],
    warnings: list[str],
    sensor_modes: Iterable[tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    """Apply sensor ingress, v-valid stream, and OTF group clock corrections."""

    workload_by_node = {item.node_id: item for item in workloads}
    for sensor_node, sensor_mode in sensor_modes:
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


def _calc_v_valid_ms(mode: dict[str, Any]) -> float | None:
    explicit = _float_or_none(mode.get("sensor_v_valid_ms") or mode.get("v_valid_ms"))
    if explicit is not None:
        return explicit
    line_length = _float_or_none(mode.get("sensor_line_length_pck") or mode.get("line_length_pck"))
    pclk = _float_or_none(mode.get("sensor_pclk") or mode.get("pclk"))
    size = _size_tuple(mode.get("active_size") or mode.get("sensor_size") or mode.get("size"))
    if line_length and pclk and size:
        return (line_length * 1000.0 / pclk) * size[1]
    fps = _float_or_none(mode.get("sensor_fps") or mode.get("fps"))
    if fps and fps > 0:
        return 1000.0 / fps
    return None


def _size_tuple(value: Any) -> tuple[int, int] | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    if isinstance(value, str) and "x" in value.lower():
        left, right = value.lower().split("x", 1)
        try:
            return int(left.strip()), int(right.strip())
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def _edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")
