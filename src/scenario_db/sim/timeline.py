from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from scenario_db.sim.models import TimelineEvent


@dataclass
class _TaskRun:
    instance_id: str
    base_id: str
    frame_index: int
    task: dict[str, Any]
    predecessors: list[str] = field(default_factory=list)
    release_ms: float = 0.0
    ready_ms: float = 0.0
    start_ms: float = 0.0
    end_ms: float = 0.0
    deadline_ms: float | None = None
    slack_ms: float | None = None
    resource_wait_ms: float = 0.0
    token_wait_ms: float = 0.0
    resource_id: str | None = None
    edge_type: str | None = None
    otf_group_id: str | None = None
    latency_offset_ms: float | None = None
    bottleneck: bool = False
    bottleneck_reason: str | None = None
    critical: bool = False
    critical_path_rank: int | None = None


def build_timeline_events(
    tasks: Iterable[dict],
    edges: Iterable[dict],
    *,
    frame_count: int = 1,
    frame_period_ms: float | None = None,
    critical_budget_ms: float | None = None,
) -> list[TimelineEvent]:
    """Build task timing events with DAG, resource, token, and frame scheduling.

    Task dicts accept:
      - id
      - node_id
      - hw_name
      - task_type: "hw" or "sw"
      - duration_ms
      - resource or resource_id
      - resource_capacity
      - release_period_ms
      - source_valid_ms or v_valid_ms
      - deadline_ms

    Edge dicts accept:
      - from/source
      - to/target
      - type: M2M, OTF, control, ...
      - duration_ms, transfer_ms, or latency_ms
      - token_resource or buffer
      - token_capacity

    The persisted `TimelineEvent` shape remains backward-compatible: existing
    consumers can keep using task_id/start/end/duration/predecessors, while
    newer consumers can inspect frame/resource/wait/critical-path fields.
    """

    try:
        import networkx as nx
        import simpy
    except ImportError as exc:
        raise RuntimeError(
            "NetworkX and SimPy are required for timeline simulation. "
            "Install the project with `uv sync --group sim`."
        ) from exc

    base_tasks = {str(task["id"]): dict(task) for task in tasks if task.get("id")}
    base_edges = [_normalized_edge(edge) for edge in edges]
    base_graph = _build_base_graph(nx, base_tasks, base_edges)
    if not nx.is_directed_acyclic_graph(base_graph):
        raise ValueError("timeline task graph must be a DAG")

    frame_count = max(1, int(frame_count or 1))
    frame_period = float(frame_period_ms or 0.0)
    runs = _expand_task_runs(base_tasks, base_graph, frame_count, frame_period)
    graph = _expand_graph(nx, base_graph, runs)
    otf_groups = _otf_groups(nx, base_graph)
    base_group_by_task = {
        task_id: f"otf-{index}"
        for index, group in enumerate(otf_groups)
        for task_id in group
    }
    instance_group_by_task = {
        run.instance_id: base_group_by_task[run.base_id]
        for run in runs.values()
        if run.base_id in base_group_by_task
    }
    for run in runs.values():
        run.otf_group_id = instance_group_by_task.get(run.instance_id)
        run.edge_type = _incoming_edge_type(run.instance_id, graph)

    env = simpy.Environment()
    resource_pool: dict[str, Any] = {}
    token_pool: dict[str, Any] = {}
    start_events: dict[str, Any] = {instance_id: env.event() for instance_id in runs}
    end_events: dict[str, Any] = {instance_id: env.event() for instance_id in runs}

    def compute_resource(resource_id: str, capacity: int):
        if resource_id not in resource_pool:
            resource_pool[resource_id] = simpy.Resource(env, capacity=max(1, capacity))
        return resource_pool[resource_id]

    def token_resource(resource_id: str, capacity: int):
        if resource_id not in token_pool:
            token_pool[resource_id] = simpy.Resource(env, capacity=max(1, capacity))
        return token_pool[resource_id]

    def run_edge_transfer(edge: dict[str, Any]):
        token_id = _edge_token_resource(edge)
        duration = _edge_duration(edge)
        if not token_id or duration <= 0:
            return 0.0
        start_wait = float(env.now)
        with token_resource(token_id, _edge_token_capacity(edge)).request() as request:
            yield request
            wait = float(env.now) - start_wait
            yield env.timeout(duration)
            return wait

    def run_edge_ready(pred_id: str, target_id: str):
        edge = graph.edges[pred_id, target_id].get("edge", {})
        dependency_event = start_events[pred_id] if _edge_is_streaming(edge) else end_events[pred_id]
        yield dependency_event
        if _edge_is_streaming(edge) and not _edge_token_resource(edge):
            duration = _edge_duration(edge)
            if duration > 0:
                yield env.timeout(duration)
            return 0.0
        return (yield from run_edge_transfer(edge))

    def finalize_run(run: _TaskRun) -> None:
        relative_deadline = _task_deadline(run.task)
        if relative_deadline is not None:
            run.deadline_ms = run.release_ms + relative_deadline
            run.slack_ms = run.deadline_ms - run.end_ms

    def run_task(instance_id: str):
        run = runs[instance_id]
        predecessor_ids = list(graph.predecessors(instance_id))
        if run.release_ms > env.now:
            yield env.timeout(run.release_ms - float(env.now))

        token_wait = 0.0
        edge_ready = []
        for pred in predecessor_ids:
            edge_ready.append(env.process(run_edge_ready(pred, instance_id)))
        if edge_ready:
            results = yield simpy.events.AllOf(env, edge_ready)
            token_wait = sum(float(value or 0.0) for value in results.values())

        run.ready_ms = float(env.now)
        run.token_wait_ms = token_wait
        duration = _task_duration(run.task)
        resource_id = _task_resource_id(run.task)
        run.resource_id = resource_id
        if resource_id:
            start_wait = float(env.now)
            with compute_resource(resource_id, _task_resource_capacity(run.task)).request() as request:
                yield request
                run.resource_wait_ms = float(env.now) - start_wait
                run.start_ms = float(env.now)
                if not start_events[instance_id].triggered:
                    start_events[instance_id].succeed(run.start_ms)
                yield env.timeout(duration)
        else:
            run.start_ms = float(env.now)
            if not start_events[instance_id].triggered:
                start_events[instance_id].succeed(run.start_ms)
            yield env.timeout(duration)
        run.end_ms = float(env.now)
        if not end_events[instance_id].triggered:
            end_events[instance_id].succeed(run.end_ms)
        finalize_run(run)

    def run_otf_group(group_instance_ids: list[str], group_id: str):
        group_runs = [runs[instance_id] for instance_id in group_instance_ids]
        release_ms = max((run.release_ms for run in group_runs), default=0.0)
        if release_ms > env.now:
            yield env.timeout(release_ms - float(env.now))

        external_ready = []
        for run in group_runs:
            for pred in graph.predecessors(run.instance_id):
                if pred not in group_instance_ids:
                    external_ready.append(env.process(run_edge_ready(pred, run.instance_id)))
        token_wait = 0.0
        if external_ready:
            results = yield simpy.events.AllOf(env, external_ready)
            token_wait = sum(float(value or 0.0) for value in results.values())

        base_start = float(env.now)
        max_duration = max((_task_duration(run.task) for run in group_runs), default=0.0)
        task_processes = []
        for run in group_runs:
            run.resource_id = _task_resource_id(run.task)
            run.ready_ms = base_start
            run.token_wait_ms = token_wait
            run.otf_group_id = group_id
            run.bottleneck = _task_duration(run.task) == max_duration
            if run.bottleneck:
                run.bottleneck_reason = "longest duration in OTF streaming group"
            task_processes.append(env.process(run_otf_group_task(run, base_start, max_duration)))
        if task_processes:
            yield simpy.events.AllOf(env, task_processes)

    def run_otf_group_task(run: _TaskRun, base_start: float, group_duration: float):
        latency_offset = _task_latency_offset(run.task)
        run.latency_offset_ms = latency_offset
        if latency_offset > 0:
            yield env.timeout(latency_offset)
        run.start_ms = base_start + latency_offset
        if not start_events[run.instance_id].triggered:
            start_events[run.instance_id].succeed(run.start_ms)
        yield env.timeout(group_duration)
        run.end_ms = float(env.now)
        if not end_events[run.instance_id].triggered:
            end_events[run.instance_id].succeed(run.end_ms)
        finalize_run(run)

    scheduled: set[str] = set()
    for frame_index in range(frame_count):
        for group_index, group in enumerate(otf_groups):
            group_id = f"otf-{group_index}#f{frame_index}" if frame_count > 1 else f"otf-{group_index}"
            group_instance_ids = [
                _instance_id(task_id, frame_index, frame_count)
                for task_id in group
                if _instance_id(task_id, frame_index, frame_count) in runs
            ]
            if not group_instance_ids:
                continue
            scheduled.update(group_instance_ids)
            env.process(run_otf_group(group_instance_ids, group_id))
    for instance_id in list(nx.topological_sort(graph)):
        if instance_id not in scheduled:
            env.process(run_task(instance_id))
    env.run()

    _mark_critical_path(runs, graph, critical_budget_ms=critical_budget_ms)
    return _timeline_events(runs, graph)


def _build_base_graph(nx, tasks: dict[str, dict[str, Any]], edges: list[dict[str, Any]]):
    graph = nx.DiGraph()
    for task_id in tasks:
        graph.add_node(task_id)
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in tasks and target in tasks:
            graph.add_edge(str(source), str(target), edge=edge)
    return graph


def _otf_groups(nx, graph) -> list[list[str]]:
    otf_edges = [
        (source, target)
        for source, target, data in graph.edges(data=True)
        if _edge_is_otf_group_edge(data.get("edge", {}))
    ]
    if not otf_edges:
        return []
    otf_graph = nx.DiGraph()
    otf_graph.add_edges_from(otf_edges)
    groups: list[list[str]] = []
    rank = {node: index for index, node in enumerate(nx.topological_sort(graph))}
    for component in nx.weakly_connected_components(otf_graph):
        groups.append(sorted((str(node) for node in component), key=lambda node: rank.get(node, 0)))
    return sorted(groups, key=lambda group: min(rank.get(node, 0) for node in group))


def _expand_task_runs(
    tasks: dict[str, dict[str, Any]],
    graph,
    frame_count: int,
    frame_period_ms: float,
) -> dict[str, _TaskRun]:
    runs: dict[str, _TaskRun] = {}
    for frame_index in range(frame_count):
        for task_id, task in tasks.items():
            release_period = float(task.get("release_period_ms") or frame_period_ms)
            release_ms = frame_index * release_period
            instance_id = _instance_id(task_id, frame_index, frame_count)
            runs[instance_id] = _TaskRun(
                instance_id=instance_id,
                base_id=task_id,
                frame_index=frame_index,
                task=task,
                predecessors=[
                    _instance_id(pred, frame_index, frame_count)
                    for pred in graph.predecessors(task_id)
                ],
                release_ms=release_ms,
            )
    return runs


def _expand_graph(nx, base_graph, runs: dict[str, _TaskRun]):
    graph = nx.DiGraph()
    for run in runs.values():
        graph.add_node(run.instance_id)
    for run in runs.values():
        for pred in run.predecessors:
            edge = base_graph.edges[runs[pred].base_id, run.base_id].get("edge", {})
            graph.add_edge(pred, run.instance_id, edge=edge)
    return graph


def _mark_critical_path(
    runs: dict[str, _TaskRun],
    graph,
    *,
    critical_budget_ms: float | None = None,
) -> None:
    if not runs:
        return
    if critical_budget_ms is not None and critical_budget_ms > 0:
        if _runs_fit_frame_budget(runs, critical_budget_ms):
            return
    by_resource: dict[str, list[_TaskRun]] = {}
    for run in runs.values():
        if run.resource_id:
            by_resource.setdefault(run.resource_id, []).append(run)
    for items in by_resource.values():
        items.sort(key=lambda item: (item.start_ms, item.end_ms, item.instance_id))

    chain: list[_TaskRun] = []
    current = max(runs.values(), key=lambda item: (item.end_ms, item.start_ms))
    while True:
        chain.append(current)
        parent = _critical_parent(current, runs, graph, by_resource)
        if parent is None:
            break
        current = parent
    chain.reverse()
    for index, run in enumerate(chain):
        run.critical = True
        run.critical_path_rank = index


def _critical_parent(
    run: _TaskRun,
    runs: dict[str, _TaskRun],
    graph,
    by_resource: dict[str, list[_TaskRun]],
) -> _TaskRun | None:
    candidates: list[tuple[float, _TaskRun]] = []
    for pred in graph.predecessors(run.instance_id):
        predecessor = runs[pred]
        edge = graph.edges[pred, run.instance_id].get("edge", {})
        if _edge_is_streaming(edge):
            ready_time = predecessor.start_ms + _edge_duration(edge)
        else:
            ready_time = predecessor.end_ms + _edge_duration(edge)
        candidates.append((ready_time, predecessor))
    if run.resource_id:
        previous_on_resource = [
            item
            for item in by_resource.get(run.resource_id, [])
            if item.instance_id != run.instance_id and item.end_ms <= run.start_ms
        ]
        if previous_on_resource:
            previous = max(previous_on_resource, key=lambda item: item.end_ms)
            candidates.append((previous.end_ms, previous))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1].start_ms))[1]


def _runs_fit_frame_budget(runs: dict[str, _TaskRun], budget_ms: float) -> bool:
    grouped: dict[str, list[_TaskRun]] = {}
    for run in runs.values():
        if run.slack_ms is not None and run.slack_ms < 0:
            return False
        if run.resource_wait_ms > 0 or run.token_wait_ms > 0:
            return False
        if run.otf_group_id:
            grouped.setdefault(run.otf_group_id, []).append(run)
        elif (run.end_ms - run.start_ms) > budget_ms:
            return False
    for group_runs in grouped.values():
        start = min(run.start_ms for run in group_runs)
        end = max(run.end_ms for run in group_runs)
        if (end - start) > budget_ms:
            return False
    return True


def _timeline_events(runs: dict[str, _TaskRun], graph) -> list[TimelineEvent]:
    result: list[TimelineEvent] = []
    rank = {node: index for index, node in enumerate(graph.nodes)}
    ordered = sorted(
        runs.values(),
        key=lambda item: (
            item.frame_index,
            item.start_ms,
            rank.get(item.instance_id, 0),
            item.end_ms,
            item.instance_id,
        ),
    )
    for run in ordered:
        task = run.task
        result.append(
            TimelineEvent(
                task_id=run.instance_id,
                node_id=task.get("node_id"),
                hw_name=task.get("hw_name"),
                task_type=task.get("task_type") or "hw",
                frame_index=run.frame_index,
                resource_id=run.resource_id,
                edge_type=run.edge_type,
                otf_group_id=run.otf_group_id,
                latency_offset_ms=run.latency_offset_ms,
                bottleneck=run.bottleneck,
                bottleneck_reason=run.bottleneck_reason or _bottleneck_reason(run),
                constraint_type=task.get("constraint_type"),
                source_fps=task.get("source_fps"),
                v_valid_ms=task.get("v_valid_ms") or task.get("source_valid_ms"),
                refresh_hz=task.get("refresh_hz"),
                scanout_ms=task.get("scanout_ms"),
                start_ms=run.start_ms,
                end_ms=run.end_ms,
                duration_ms=run.end_ms - run.start_ms,
                deadline_ms=run.deadline_ms,
                slack_ms=run.slack_ms,
                ready_ms=run.ready_ms,
                resource_wait_ms=run.resource_wait_ms,
                token_wait_ms=run.token_wait_ms,
                critical=run.critical,
                critical_path_rank=run.critical_path_rank,
                predecessors=list(graph.predecessors(run.instance_id)),
            )
        )
    return result


def _bottleneck_reason(run: _TaskRun) -> str | None:
    if run.bottleneck:
        return "longest duration in OTF streaming group"
    if run.resource_wait_ms > 0:
        return "waited for shared resource"
    if run.token_wait_ms > 0:
        return "waited for M2M/VOTF token queue"
    if run.slack_ms is not None and run.slack_ms < 0:
        return "missed sink deadline"
    if run.critical:
        return "on critical path after frame-budget check"
    return None


def _incoming_edge_type(instance_id: str, graph) -> str | None:
    incoming = list(graph.predecessors(instance_id))
    if not incoming:
        return None
    edge_types = [
        str((graph.edges[pred, instance_id].get("edge", {}) or {}).get("type") or "")
        for pred in incoming
    ]
    edge_types = [edge_type for edge_type in edge_types if edge_type]
    if not edge_types:
        return None
    if len(set(edge_types)) == 1:
        return edge_types[0]
    return ",".join(edge_types)


def _normalized_edge(edge: dict[str, Any]) -> dict[str, Any]:
    result = dict(edge)
    result["source"] = edge.get("from") if edge.get("from") is not None else edge.get("source")
    result["target"] = edge.get("to") if edge.get("to") is not None else edge.get("target")
    return result


def _task_resource_id(task: dict[str, Any]) -> str | None:
    explicit = task.get("resource_id") or task.get("resource")
    if explicit:
        return str(explicit)
    if str(task.get("task_type") or "hw").lower() == "hw" and task.get("hw_name"):
        return str(task["hw_name"])
    return None


def _task_resource_capacity(task: dict[str, Any]) -> int:
    return int(task.get("resource_capacity") or task.get("capacity") or 1)


def _task_duration(task: dict[str, Any]) -> float:
    duration = task.get("duration_ms")
    if duration is None or float(duration or 0.0) <= 0.0:
        duration = task.get("source_valid_ms") or task.get("v_valid_ms")
    return float(duration or 0.0)


def _task_latency_offset(task: dict[str, Any]) -> float:
    return float(task.get("latency_offset_ms") or task.get("latency_ms") or 0.0)


def _task_deadline(task: dict[str, Any]) -> float | None:
    value = task.get("deadline_ms")
    if value is None:
        value = task.get("sink_deadline_ms")
    if value is None:
        return None
    return float(value)


def _edge_token_resource(edge: dict[str, Any]) -> str | None:
    explicit = edge.get("token_resource") or edge.get("queue_resource")
    if explicit:
        return str(explicit)
    edge_type = str(edge.get("type") or "").upper()
    if edge_type in {"M2M", "VOTF"}:
        return f"{edge_type}:{edge.get('buffer') or edge.get('source')}->{edge.get('target')}"
    return None


def _edge_token_capacity(edge: dict[str, Any]) -> int:
    return int(edge.get("token_capacity") or edge.get("queue_capacity") or 1)


def _edge_duration(edge: dict[str, Any]) -> float:
    return float(
        edge.get("duration_ms")
        or edge.get("transfer_ms")
        or edge.get("latency_ms")
        or edge.get("line_delay_ms")
        or 0.0
    )


def _edge_is_streaming(edge: dict[str, Any]) -> bool:
    return str(edge.get("type") or "").upper() in {"OTF", "VOTF"}


def _edge_is_otf_group_edge(edge: dict[str, Any]) -> bool:
    return str(edge.get("type") or "").upper() == "OTF"


def _instance_id(task_id: str, frame_index: int, frame_count: int) -> str:
    if frame_count == 1:
        return task_id
    return f"{task_id}#f{frame_index}"
