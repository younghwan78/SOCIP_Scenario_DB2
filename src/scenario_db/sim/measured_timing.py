"""Apply a measured timing profile to timeline inputs without mutating a scenario."""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
    from scenario_db.models.evidence.profiling import MeasuredTimingProfile


def apply_measured_timing(graph: CanonicalScenarioGraph, profile: MeasuredTimingProfile,
                          tasks: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict]]:
    if (profile.project_ref, profile.scenario_ref, profile.variant_ref) != (
            graph.scenario.project_ref, graph.scenario_id, graph.variant_id):
        raise ValueError("timing profile project/scenario/variant scope mismatch")
    if profile.design_conditions != (graph.variant.design_conditions or {}):
        raise ValueError("timing profile design conditions mismatch; remeasurement or calibrated projection required")
    tasks, edges = deepcopy(tasks), deepcopy(edges)
    by_id = {str(t['id']): t for t in tasks}
    for node, stats in profile.task_runtime.items():
        if node not in by_id:
            raise ValueError(f"timing profile task is inactive or collapsed: {node}")
        by_id[node]['duration_ms'] = getattr(stats, f'{profile.statistic}_ms')
        by_id[node]['measured_duration'] = True
    for latency in profile.event_latency:
        if latency.source_anchor != 'end':
            raise ValueError('simulation only supports end-to-start latency')
        matches = [e for e in edges
                   if str(e.get('from') or e.get('source')) == latency.predecessor_task
                   and str(e.get('to') or e.get('target')) == latency.successor_task]
        if len(matches) != 1:
            raise ValueError(f"timing profile edge must resolve uniquely: {latency.edge_id}")
        # Replaces the existing release delay; never adds the same measured wait twice.
        matches[0]['latency_ms'] = getattr(latency, f'{profile.statistic}_ms')
    return tasks, edges


def baseline_fingerprint(graph: CanonicalScenarioGraph) -> str:
    """Bind replay to effective topology, resolved variant and catalog contents."""
    import hashlib
    import json
    from dataclasses import asdict
    # R-3 event jobs are not steady inputs: declaring or editing them keeps a steady replay valid
    from scenario_db.models.definition.job import steady_pipeline
    from scenario_db.sim.jobs import steady_variant_doc

    pipeline = steady_pipeline(graph.scenario.pipeline)
    variant = steady_variant_doc(asdict(graph.variant))           # the job measured slots (sim.jobs) too
    payload = dict(project_ref=graph.scenario.project_ref, scenario_id=graph.scenario_id,
                   pipeline=pipeline, size_profile=graph.scenario.size_profile, variant=variant,
                   project=dict(metadata=graph.project.metadata_, globals=graph.project.globals_) if graph.project else None,
                   ips={key:dict(category=row.category, capabilities=row.capabilities)
                        for key,row in sorted(graph.ip_catalog.items())},
                   soc=dict(compression_modes=graph.soc.compression_modes,
                            platform_model=graph.soc.platform_model) if graph.soc else None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
