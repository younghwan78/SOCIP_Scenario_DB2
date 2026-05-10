from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.sim.external_devices import apply_source_sink_constraints


def timeline_tasks(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
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
        return apply_source_sink_constraints(graph, tasks, nodes)
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
    return apply_source_sink_constraints(graph, tasks, graph.pipeline_nodes)


def timeline_edges(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    task_graph = (graph.scenario.pipeline or {}).get("task_graph") or {}
    return list(task_graph.get("edges") or graph.pipeline_edges)


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
