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
from scenario_db.sim.transfers import compression_catalog, edge_port_transfers, history_port_transfers, port_transfers_for_node, standalone_port_transfers
from scenario_db.sim.stream_io import supplemental_transfers
from scenario_db.sim.timing_profiles import timing_case, timing_profiles
from scenario_db.sim.workloads import build_workload_for_node, node_sim_block


def build_simulation_inputs(
    graph: CanonicalScenarioGraph,
    config: SimulationRunConfig | None = None,
) -> SimulationInputs:
    """Convert an effective canonical graph into simulation-engine inputs."""

    run_config = config or SimulationRunConfig()
    if run_config.timing_profile is not None and run_config.sw_timing_projection is not None:
        raise ValueError("select measured replay or SW projection, not both")
    if run_config.timing_profile is not None:
        from scenario_db.sim.measured_timing import baseline_fingerprint
        pinned = run_config.timing_profile.baseline_sha256
        if pinned is not None and pinned != baseline_fingerprint(graph):
            raise ValueError("timing profile baseline changed; rebuild and review the profile")
        if run_config.fps is not None and run_config.fps != (graph.variant.design_conditions or {}).get("fps"):
            raise ValueError("measured timing profile does not support FPS extrapolation")
        from copy import deepcopy
        from dataclasses import replace
        variant = deepcopy(graph.variant)
        variant.node_configs = variant.node_configs or {}
        for node, stats in run_config.timing_profile.task_runtime.items():
            node_config = variant.node_configs.get(node, {})
            if node_config.get("sw_timing"):
                previous = node_config["sw_timing"]
                node_config["sw_timing"] = {**previous, **stats.model_dump(), "value_source": "measured"}
                for stale in ("p50_ms", "p95_ms"):
                    node_config["sw_timing"].pop(stale, None)
                # Captured duration already includes the captured bitrate; do not rescale it again.
                node_config.pop("sw_bitrate_scaling", None)
        graph = replace(graph, variant=variant)
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
    transfers.extend(standalone_port_transfers(graph, {item.node_id: item for item in workloads}, comp_catalog, warnings))
    transfers.extend(supplemental_transfers(graph))
    for node_id, profile in timing_profiles(graph).items():
        if profile.get("start_latency_ref"):
            warnings.append(f"{node_id}: named event {profile['start_latency_ref']} is metadata only; select an explicitly mapped measured timing profile to apply its latency.")
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
        selected_case = (run_config.timing_profile.statistic if run_config.timing_profile
                         and stage in run_config.timing_profile.task_runtime else timing_case(graph))
        budget = float(profile[f"{selected_case}_ms"])
        for node_id in profile.get("includes_hw_nodes", []):
            workload = by_node.get(node_id)
            if workload is None or workload.sim_params.ppc <= 0 or budget <= 0:
                raise ValueError(f"{stage}: included hardware needs positive PPC and a time budget")
            bound = workload.pixels * (1 + run_config.h_blank_margin) / (budget * workload.sim_params.ppc * 1000)
            if bound > workload.clock_correction_mhz:
                workload.clock_correction_mhz = bound
                workload.clock_correction_reason = f"included_stage_budget({stage}, {budget:g}ms; lower bound)"


    tasks, edges = timeline_tasks(graph), timeline_edges(graph)
    sw_profiles = timing_profiles(graph)
    if run_config.timing_profile is not None:
        from scenario_db.sim.measured_timing import apply_measured_timing
        tasks, edges = apply_measured_timing(graph, run_config.timing_profile, tasks, edges)
        for node, stats in run_config.timing_profile.task_runtime.items():
            if node in sw_profiles:
                sw_profiles[node] = {**sw_profiles[node], **stats.model_dump(), "value_source": "measured",
                                     "source_note": f"timing profile {run_config.timing_profile.profile_id}@{run_config.timing_profile.revision}"}
                for stale in ("p50_ms", "p95_ms"):
                    sw_profiles[node].pop(stale, None)
        warnings.append("Measured timing profile applies at captured conditions only; wall time does not calibrate active power.")

    if run_config.sw_timing_projection is not None:
        from scenario_db.sim.sw_projection import apply_projection
        tasks, edges, sw_profiles = apply_projection(graph, run_config.sw_timing_projection, tasks, edges, sw_profiles)
        warnings.append("Projected SW elapsed time and observed gaps are assumptions; CPU active power is not calibrated.")

    return SimulationInputs(
        scenario_id=graph.scenario_id,
        variant_id=graph.variant_id,
        project_ref=getattr(graph.scenario, "project_ref", None),
        config=run_config.model_copy(update={"fps": fps}),
        workloads=workloads,
        port_transfers=transfers,
        timeline_tasks=tasks,
        timeline_edges=edges,
        sw_task_timing=list(sw_profiles.values()),
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
