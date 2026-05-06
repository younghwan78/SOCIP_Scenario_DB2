from __future__ import annotations

from collections.abc import Iterable

from scenario_db.sim.models import TimelineEvent


def build_timeline_events(tasks: Iterable[dict], edges: Iterable[dict]) -> list[TimelineEvent]:
    """Build deterministic task timing events with NetworkX ordering and SimPy time.

    This is the first ScenarioDB-native hook for SW-task-inclusive timing evidence.
    Each task dict accepts:
      - id
      - node_id
      - hw_name
      - task_type: "hw" or "sw"
      - duration_ms

    The current implementation models precedence only. Resource contention and
    queue/token behavior can be added without changing the stored event shape.
    """

    try:
        import networkx as nx
        import simpy
    except ImportError as exc:
        raise RuntimeError(
            "NetworkX and SimPy are required for timeline simulation. "
            "Install the project with `uv sync --group sim`."
        ) from exc

    graph = nx.DiGraph()
    task_map = {str(task["id"]): dict(task) for task in tasks}
    for task_id in task_map:
        graph.add_node(task_id)
    for edge in edges:
        source = edge.get("from") if edge.get("from") is not None else edge.get("source")
        target = edge.get("to") if edge.get("to") is not None else edge.get("target")
        if source in task_map and target in task_map:
            graph.add_edge(str(source), str(target))

    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("timeline task graph must be a DAG")

    env = simpy.Environment()
    complete_at: dict[str, float] = {}
    events: dict[str, object] = {}

    def run_task(task_id: str):
        predecessors = list(graph.predecessors(task_id))
        if predecessors:
            yield simpy.events.AllOf(env, [events[pred] for pred in predecessors])
        start = float(env.now)
        duration = float(task_map[task_id].get("duration_ms") or 0.0)
        yield env.timeout(duration)
        complete_at[task_id] = float(env.now)

    for task_id in nx.topological_sort(graph):
        events[task_id] = env.process(run_task(task_id))
    env.run()

    result: list[TimelineEvent] = []
    for task_id in nx.topological_sort(graph):
        task = task_map[task_id]
        predecessors = list(graph.predecessors(task_id))
        start = max((complete_at[pred] for pred in predecessors), default=0.0)
        end = complete_at.get(task_id, start)
        result.append(
            TimelineEvent(
                task_id=task_id,
                node_id=task.get("node_id"),
                hw_name=task.get("hw_name"),
                task_type=task.get("task_type") or "hw",
                start_ms=start,
                end_ms=end,
                duration_ms=end - start,
                predecessors=predecessors,
            )
        )
    return result

