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
    resource_wait_ms: float = 0.0
    token_wait_ms: float = 0.0
    resource_id: str | None = None
    critical: bool = False
    critical_path_rank: int | None = None


def build_timeline_events(
    tasks: Iterable[dict],
    edges: Iterable[dict],
    *,
    frame_count: int = 1,
    frame_period_ms: float | None = None,
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

    env = simpy.Environment()
    resource_pool: dict[str, Any] = {}
    token_pool: dict[str, Any] = {}
    processes: dict[str, Any] = {}

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

    def run_task(instance_id: str):
        run = runs[instance_id]
        predecessor_ids = list(graph.predecessors(instance_id))
        if predecessor_ids:
            yield simpy.events.AllOf(env, [processes[pred] for pred in predecessor_ids])
        if run.release_ms > env.now:
            yield env.timeout(run.release_ms - float(env.now))

        token_wait = 0.0
        transfers = []
        for pred in predecessor_ids:
            edge = graph.edges[pred, instance_id].get("edge", {})
            transfers.append(env.process(run_edge_transfer(edge)))
        if transfers:
            results = yield simpy.events.AllOf(env, transfers)
            token_wait = sum(float(value or 0.0) for value in results.values())

        run.ready_ms = float(env.now)
        run.token_wait_ms = token_wait
        duration = float(run.task.get("duration_ms") or 0.0)
        resource_id = _task_resource_id(run.task)
        run.resource_id = resource_id
        if resource_id:
            start_wait = float(env.now)
            with compute_resource(resource_id, _task_resource_capacity(run.task)).request() as request:
                yield request
                run.resource_wait_ms = float(env.now) - start_wait
                run.start_ms = float(env.now)
                yield env.timeout(duration)
        else:
            run.start_ms = float(env.now)
            yield env.timeout(duration)
        run.end_ms = float(env.now)

    for instance_id in list(nx.topological_sort(graph)):
        processes[instance_id] = env.process(run_task(instance_id))
    env.run()

    _mark_critical_path(runs, graph)
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


def _expand_task_runs(
    tasks: dict[str, dict[str, Any]],
    graph,
    frame_count: int,
    frame_period_ms: float,
) -> dict[str, _TaskRun]:
    runs: dict[str, _TaskRun] = {}
    for frame_index in range(frame_count):
        release_ms = frame_index * frame_period_ms
        for task_id, task in tasks.items():
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


def _mark_critical_path(runs: dict[str, _TaskRun], graph) -> None:
    if not runs:
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
    candidates = [runs[pred] for pred in graph.predecessors(run.instance_id)]
    if run.resource_id:
        previous_on_resource = [
            item
            for item in by_resource.get(run.resource_id, [])
            if item.instance_id != run.instance_id and item.end_ms <= run.start_ms
        ]
        if previous_on_resource:
            candidates.append(max(previous_on_resource, key=lambda item: item.end_ms))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.end_ms, item.start_ms))


def _timeline_events(runs: dict[str, _TaskRun], graph) -> list[TimelineEvent]:
    result: list[TimelineEvent] = []
    ordered = sorted(runs.values(), key=lambda item: (item.frame_index, item.start_ms, item.end_ms, item.instance_id))
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
                start_ms=run.start_ms,
                end_ms=run.end_ms,
                duration_ms=run.end_ms - run.start_ms,
                ready_ms=run.ready_ms,
                resource_wait_ms=run.resource_wait_ms,
                token_wait_ms=run.token_wait_ms,
                critical=run.critical,
                critical_path_rank=run.critical_path_rank,
                predecessors=list(graph.predecessors(run.instance_id)),
            )
        )
    return result


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


def _edge_token_resource(edge: dict[str, Any]) -> str | None:
    explicit = edge.get("token_resource") or edge.get("queue_resource")
    if explicit:
        return str(explicit)
    edge_type = str(edge.get("type") or "").upper()
    if edge_type in {"M2M", "OTF", "VOTF"}:
        return f"{edge_type}:{edge.get('buffer') or edge.get('source')}->{edge.get('target')}"
    return None


def _edge_token_capacity(edge: dict[str, Any]) -> int:
    return int(edge.get("token_capacity") or edge.get("queue_capacity") or 1)


def _edge_duration(edge: dict[str, Any]) -> float:
    return float(edge.get("duration_ms") or edge.get("transfer_ms") or edge.get("latency_ms") or 0.0)


def _instance_id(task_id: str, frame_index: int, frame_count: int) -> str:
    if frame_count == 1:
        return task_id
    return f"{task_id}#f{frame_index}"
