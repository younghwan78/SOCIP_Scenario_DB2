"""Wall-time assumptions shared by variant timing and evidence reporting."""
from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.models.evidence.measurement import SwTaskTiming


def timing_profiles(graph: CanonicalScenarioGraph) -> dict[str, dict[str, Any]]:
    active = {str(n["id"]) for n in graph.pipeline_nodes}
    profiles = {}
    for node_id, config in (graph.variant.node_configs or {}).items():
        raw = config.get("sw_timing") if isinstance(config, dict) else None
        if node_id not in active or not raw:
            continue
        profile = SwTaskTiming.model_validate({"task": node_id, **raw}).model_dump(exclude_none=True)
        low, mean, high = (profile.get(k) for k in ("min_ms", "mean_ms", "max_ms"))
        if low is None or mean is None or high is None or not low <= mean <= high:
            raise ValueError(f"{node_id}: timing must satisfy 0 <= min_ms <= mean_ms <= max_ms")
        if any(child not in active for child in profile.get("includes_hw_nodes", [])):
            raise ValueError(f"{node_id}: included hardware must be active")
        profiles[node_id] = profile
    return profiles


def timing_case(graph: CanonicalScenarioGraph) -> str:
    case = str((graph.variant.design_conditions or {}).get("sw_timing_case", "mean"))
    if case not in {"min", "mean", "max"}:
        raise ValueError("sw_timing_case must be min, mean, or max")
    return case


def collapsed_hardware(profiles: dict[str, dict[str, Any]]) -> dict[str, str]:
    owners = {}
    for stage, profile in profiles.items():
        for child in profile.get("includes_hw_nodes", []):
            if child == stage or child in owners or child in profiles:
                raise ValueError(f"{child}: overlapping or nested timing stages are unsupported")
            owners[child] = stage
    return owners
