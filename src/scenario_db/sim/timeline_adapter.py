from __future__ import annotations

from typing import Any, cast

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.external_devices import apply_source_sink_constraints
from scenario_db.sim.timing_profiles import collapsed_hardware, timing_case, timing_profiles


def timeline_tasks(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    task_graph = cast(dict[str, Any], graph.scenario.pipeline or {}).get("task_graph") or {}
    nodes = task_graph.get("nodes") or []
    if nodes:
        tasks = [
            {
                "id": str(node.get("id")),
                "node_id": node.get("id"),
                "hw_name": _label_hw_name(node),
                "task_type": "sw" if str(node.get("layer") or "").lower() in {"app", "framework", "hal", "kernel"} else "hw",
                "duration_ms": node.get("duration_ms") or node.get("manual_hw_time_ms") or 0.0,
                "resource_id": node.get("resource_id") or node.get("resource") or (
                    str(node["id"]) if str(node.get("layer") or "").lower()
                    not in {"app", "framework", "hal", "kernel"} else None
                ),
                "resource_capacity": node.get("resource_capacity") or 1,
            }
            for node in nodes
            if node.get("id")
        ]
        return apply_source_sink_constraints(graph, tasks, nodes)
    profiles = timing_profiles(graph)
    owners = collapsed_hardware(profiles)
    case = timing_case(graph)
    tasks = [
        {
            "id": str(node.get("id")),
            "node_id": node.get("id"),
            "hw_name": _fallback_hw_name(str(node.get("ip_ref") or node.get("id"))),
            "task_type": "sw" if str(node.get("role")) == "sw_task" else "hw",
            "duration_ms": profiles.get(str(node["id"]), {}).get(f"{case}_ms", 0.0),
            "resource_id": ("stage:" + str(node["id"]) if profiles.get(str(node["id"]), {}).get("includes_hw_nodes") else "CPU_CAMERA" if node.get("role") == "sw_task" else node.get("resource_id") or node.get("resource") or str(node["id"])),
            "resource_capacity": node.get("resource_capacity") or 1,
        }
        for node in graph.pipeline_nodes
        if node.get("id") and str(node["id"]) not in owners
    ]
    return apply_source_sink_constraints(graph, tasks, graph.pipeline_nodes)


def timeline_edges(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    task_graph = cast(dict[str, Any], graph.scenario.pipeline or {}).get("task_graph") or {}
    if task_graph.get("edges"):
        return list(task_graph["edges"])
    profiles = timing_profiles(graph)
    owners = collapsed_hardware(profiles)
    edges = []
    seen = set()
    for raw in graph.pipeline_edges:
        edge = dict(raw)
        source = str(edge.get("from") or edge.get("source"))
        target = str(edge.get("to") or edge.get("target"))
        edge["from"] = owners.get(source, source)
        edge["to"] = owners.get(target, target)
        if edge["from"] == edge["to"]:
            continue
        key = (edge["from"], edge["to"], edge.get("type"))
        if key in seen:
            continue
        seen.add(key)
        # Jitter is release delay, not CPU execution time. Only its mean is supplied.
        delay = profiles.get(target, {}).get("start_jitter_mean_ms", 0.0)
        if delay:
            edge["latency_ms"] = delay
        edges.append(edge)
    return edges


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
