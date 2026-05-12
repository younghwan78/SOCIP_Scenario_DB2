from __future__ import annotations

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.clock_corrections import apply_sensor_otf_clock_corrections
from scenario_db.sim.external_devices import (
    active_sensor_nodes,
    external_devices,
    selected_sensor_mode,
)
from scenario_db.sim.models import SimulationInputs, SimulationRunConfig
from scenario_db.sim.shape_propagation import propagate_shapes
from scenario_db.sim.timeline_adapter import timeline_edges, timeline_tasks
from scenario_db.sim.transfers import edge_port_transfers, port_transfers_for_node
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
                workload.ip_ref,
                workload.hw_name,
                node_sim_block(graph, workload.node_id),
                shape=shapes.node(workload.node_id),
            )
        )

    if not transfers:
        transfers.extend(edge_port_transfers(graph, {item.node_id: item for item in workloads}))

    sensor_modes = [
        (sensor_node, sensor_mode)
        for sensor_node in active_sensor_nodes(graph)
        if (sensor_mode := selected_sensor_mode(graph, sensor_node))
    ]
    apply_sensor_otf_clock_corrections(graph, workloads, warnings, sensor_modes)

    return SimulationInputs(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        project_ref=getattr(graph.scenario, "project_ref", None),
        config=run_config.model_copy(update={"fps": fps}),
        workloads=workloads,
        port_transfers=transfers,
        timeline_tasks=timeline_tasks(graph),
        timeline_edges=timeline_edges(graph),
        external_devices=external_devices(graph),
        topology_order=[item.node_id for item in workloads],
        warnings=warnings,
    )


def _fps(graph: CanonicalScenarioGraph, config: SimulationRunConfig) -> float:
    if config.fps is not None:
        return float(config.fps)
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or 30.0)
