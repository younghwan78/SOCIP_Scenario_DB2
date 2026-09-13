from __future__ import annotations

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.clock_corrections import apply_sensor_otf_clock_corrections
from scenario_db.sim.external_devices import (
    active_sensor_nodes,
    external_devices,
    selected_sensor_mode,
)
from scenario_db.sim.models import IPWorkload, PortTransferSpec, SimulationInputs, SimulationRunConfig
from scenario_db.sim.shape_propagation import propagate_shapes, validate_shape_propagation
from scenario_db.sim.timeline_adapter import timeline_edges, timeline_tasks
from scenario_db.sim.transfers import compression_catalog, edge_port_transfers, history_port_transfers, port_transfers_for_node
from scenario_db.sim.timing_profiles import timing_case, timing_profiles
from scenario_db.sim.workloads import build_workload_for_node, node_sim_block


def build_simulation_inputs(
    graph: CanonicalScenarioGraph,
    config: SimulationRunConfig | None = None,
) -> SimulationInputs:
    """Convert an effective canonical graph into simulation-engine inputs."""

    run_config = config or SimulationRunConfig()
    fps = _fps(graph, run_config)
    shapes = propagate_shapes(graph)
    workloads: list[IPWorkload] = []
    transfers: list[PortTransferSpec] = []
    warnings: list[str] = []
    warnings.extend(validate_shape_propagation(graph, shapes))
    _append_missing_ip_catalog_warnings(graph, warnings)
    comp_catalog = compression_catalog(graph.soc)

    for node in graph.pipeline_nodes:
        node_id = str(node.get("id") or "")
        workload = build_workload_for_node(
            graph,
            node,
            fps=fps,
            run_config=run_config,
            warnings=warnings,
            shape=shapes.node(node_id),
        )
        if workload is None:
            continue
        workloads.append(workload)
        transfers.extend(
            port_transfers_for_node(
                workload.node_id,
                str(workload.ip_ref),
                workload.hw_name,
                node_sim_block(graph, workload.node_id),
                shape=shapes.node(workload.node_id),
                comp_catalog=comp_catalog,
                warnings=warnings,
            )
        )

    explicit_nodes = {item.node_id for item in transfers}
    transfers.extend(item for item in edge_port_transfers(
            graph,
            {item.node_id: item for item in workloads},
            comp_catalog=comp_catalog,
            warnings=warnings,
        ) if item.node_id not in explicit_nodes)
    transfers.extend(history_port_transfers(graph, {item.node_id: item for item in workloads}, comp_catalog, warnings))
    for node_id, profile in timing_profiles(graph).items():
        if profile.get("value_source") == "assumed":
            warnings.append(f"{node_id}: assumed wall time; not a measured CPU active-time/power value.")
    if (graph.variant.design_conditions or {}).get("sensor_support"):
        warnings.append("Requested sensor size/fps is unverified for this variant; do not use as a validated operating point.")

    sensor_modes = [
        (sensor_node, sensor_mode)
        for sensor_node in active_sensor_nodes(graph)
        if (sensor_mode := selected_sensor_mode(graph, sensor_node))
    ]
    apply_sensor_otf_clock_corrections(graph, workloads, warnings, sensor_modes)
    # Included hardware must fit its aggregate wall-time budget. This is a lower
    # clock bound: CPU/HW overlap inside that interval is not characterized.
    by_node = {item.node_id: item for item in workloads}
    for stage, profile in timing_profiles(graph).items():
        budget = float(profile[f"{timing_case(graph)}_ms"])
        for node_id in profile.get("includes_hw_nodes", []):
            workload = by_node.get(node_id)
            if workload is None or workload.sim_params.ppc <= 0 or budget <= 0:
                raise ValueError(f"{stage}: included hardware needs positive PPC and a time budget")
            bound = workload.pixels * (1 + run_config.h_blank_margin) / (budget * workload.sim_params.ppc * 1000)
            if bound > workload.clock_correction_mhz:
                workload.clock_correction_mhz = bound
                workload.clock_correction_reason = f"included_stage_budget({stage}, {budget:g}ms; lower bound)"


    return SimulationInputs(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        project_ref=getattr(graph.scenario, "project_ref", None),
        config=run_config.model_copy(update={"fps": fps}),
        workloads=workloads,
        port_transfers=transfers,
        timeline_tasks=timeline_tasks(graph),
        timeline_edges=timeline_edges(graph),
        sw_task_timing=list(timing_profiles(graph).values()),
        external_devices=external_devices(graph),
        topology_order=[item.node_id for item in workloads],
        warnings=warnings,
    )


def _fps(graph: CanonicalScenarioGraph, config: SimulationRunConfig) -> float:
    if config.fps is not None:
        return float(config.fps)
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or 30.0)


def _append_missing_ip_catalog_warnings(graph: CanonicalScenarioGraph, warnings: list[str]) -> None:
    seen: set[tuple[str, str]] = set()
    for node in graph.pipeline_nodes:
        node_id = str(node.get("id") or "")
        ip_ref = str(node.get("ip_ref") or "")
        if not node_id or not ip_ref or ip_ref in graph.ip_catalog:
            continue
        key = (node_id, ip_ref)
        if key in seen:
            continue
        seen.add(key)
        warnings.append(
            f"{node_id} references ip_ref '{ip_ref}' that is not present in the selected DB catalog; "
            "simulation workload, power, and timing for this node will be skipped."
        )
