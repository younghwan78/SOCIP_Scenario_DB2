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
            "task_type": "sw" if str(node.get("role")) == "sw_task" or str(node["id"]) in profiles else "hw",
            "duration_ms": profiles.get(str(node["id"]), {}).get(f"{case}_ms", 0.0),
            "resource_id": (graph.variant.node_configs or {}).get(str(node["id"]), {}).get("timeline_resource_id") or ("stage:" + str(node["id"]) if profiles.get(str(node["id"]), {}).get("includes_hw_nodes") else "CPU_CAMERA" if node.get("role") == "sw_task" else node.get("resource_id") or node.get("resource") or str(node["id"])),
            "resource_capacity": node.get("resource_capacity") or 1,
        }
        for node in graph.pipeline_nodes
        if node.get("id") and str(node["id"]) not in owners
    ]
    for task in tasks:
        _apply_cadence(task, (graph.variant.node_configs or {}).get(str(task["id"])) or {})
    out = apply_source_sink_constraints(graph, tasks, graph.pipeline_nodes)
    _resolve_vsync(out)
    return out


# D-04: the hand-off cadence vocabulary (sdb.handoff/1) as the simulation task model.
#   frame   = released with the variant frame (the default; part of the frame DAG)
#   period  = own fixed period (ABOX period IRQ, ExoPlayer work loop …)
#   chunk   = released once per chunk (writer flush, network segment …); like period, named for what it is
#   vsync   = the display refresh (``refresh_hz``, else the panel's selected refresh)
#   divided = every N-th frame (``every``): a 6 fps M2M on a 30 fps stream
#   event   = released once (``phase_ms``): capture, a one-off request
CADENCE_KINDS = ("frame", "period", "chunk", "vsync", "divided", "event")


def own_cadence(task: dict[str, Any]) -> bool:
    """A task released on its own cadence, outside the frame DAG and the frame stages."""
    return bool(task.get("independent_period_ms") or task.get("independent_every") or task.get("independent_once")
                or task.get("independent_vsync"))


def _apply_cadence(task: dict[str, Any], config: dict[str, Any]) -> None:
    """Own cadence from ``node_configs.<node>.timeline``.

    Without ``cadence`` a ``period_ms`` keeps the previous meaning: an own period outside the frame DAG,
    not judged. With ``cadence`` (one of :data:`CADENCE_KINDS`) the task is also judged against its own
    deadline: ``deadline_ms``, else its period (event: only when ``deadline_ms`` is given).
    ``duration_ms`` is used when no calculated HW time exists for the node.
    """
    timeline = config.get("timeline") or {}
    kind = timeline.get("cadence")
    period = float(timeline.get("period_ms") or 0.0)
    node = task.get("id")
    if kind is None:
        if period <= 0:
            return
        task["independent_period_ms"] = period
    else:
        if kind not in CADENCE_KINDS:
            raise ValueError(f"{node}: timeline.cadence {kind!r} is not one of {', '.join(CADENCE_KINDS)}")
        if kind == "frame":
            return
        task["cadence"] = kind
        if kind in ("period", "chunk"):
            if period <= 0:
                raise ValueError(f"{node}: timeline.cadence {kind} needs period_ms > 0")
            task["independent_period_ms"] = period
        elif kind == "vsync":
            hz = float(timeline.get("refresh_hz") or 0.0)
            if hz > 0:
                task["independent_period_ms"] = 1000.0 / hz
            else:
                task["independent_vsync"] = True  # the panel's refresh, resolved after the sink constraints
        elif kind == "divided":
            every = int(timeline.get("every") or 0)
            if every < 2:
                raise ValueError(f"{node}: timeline.cadence divided needs every >= 2 (frames per release)")
            task["independent_every"] = every
        else:  # event
            task["independent_once"] = True
        if timeline.get("deadline_ms") is not None:
            deadline = float(timeline["deadline_ms"])
            if deadline <= 0:
                raise ValueError(f"{node}: timeline.deadline_ms must be > 0")
            task["deadline_ms"] = deadline
        elif kind in ("period", "chunk") or (kind == "vsync" and task.get("independent_period_ms")):
            task["deadline_ms"] = task["independent_period_ms"]
        # divided / vsync from the panel: the deadline is the resolved period (timeline / _resolve_vsync)
    if timeline.get("phase_ms") is not None:
        task["independent_phase_ms"] = float(timeline["phase_ms"])
    if not float(task.get("duration_ms") or 0.0) and timeline.get("duration_ms") is not None:
        task["duration_ms"] = float(timeline["duration_ms"])


def _resolve_vsync(tasks: list[dict[str, Any]]) -> None:
    pending = [t for t in tasks if t.get("independent_vsync")]
    if not pending:
        return
    refresh = next((float(t["refresh_hz"]) for t in tasks if t.get("refresh_hz")), 0.0)
    for task in pending:
        if refresh <= 0:
            raise ValueError(f"{task.get('id')}: timeline.cadence vsync needs refresh_hz (no panel refresh in this variant)")
        task.pop("independent_vsync")
        task["independent_period_ms"] = 1000.0 / refresh
        task.setdefault("deadline_ms", task["independent_period_ms"])


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
