"""Shared pipeline graph helpers and checks.

Canonical home for edge accessors (from/source, to/target aliases), edge
matching semantics, and the data-flow cycle check. Data-flow edges
(OTF/vOTF/M2M) must form a DAG; control edges are allowed to close loops
(SW feedback paths). Used by variant overlay resolution, write validation,
import bundle validation, and explorer import-health.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

DATA_FLOW_EDGE_TYPES = {"OTF", "vOTF", "M2M"}


def edge_source(edge: dict[str, Any]) -> Any:
    return edge.get("from") if edge.get("from") is not None else edge.get("source")


def edge_target(edge: dict[str, Any]) -> Any:
    return edge.get("to") if edge.get("to") is not None else edge.get("target")


def edge_matches(edge: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Canonical remove-edge spec matching.

    Matches by id, or by (from, to) endpoints; when the spec also carries
    type and/or buffer, those must match too, so a spec targeting one of
    several parallel edges (e.g. OTF + control on the same node pair) does
    not remove its siblings.
    """
    spec_id = spec.get("id")
    if spec_id and spec_id == edge.get("id"):
        return True
    if edge_source(edge) != edge_source(spec) or edge_target(edge) != edge_target(spec):
        return False
    for field in ("type", "buffer"):
        if spec.get(field) is not None and edge.get(field) != spec.get(field):
            return False
    return True


def normalize_edge(edge: Any) -> dict[str, Any]:
    """Return a copy of the edge with source/target aliased to from/to."""
    if not isinstance(edge, dict):
        return {}
    normalized = deepcopy(edge)
    if "source" in normalized and "from" not in normalized:
        normalized["from"] = normalized.pop("source")
    if "target" in normalized and "to" not in normalized:
        normalized["to"] = normalized.pop("target")
    return normalized


def find_data_flow_cycle(
    nodes: list[Any],
    edges: list[Any],
) -> list[str] | None:
    """Return one data-flow cycle as a node id path (closed: first == last), or None.

    Only edges whose type is in DATA_FLOW_EDGE_TYPES and whose endpoints both
    exist participate. Kahn's algorithm finds whether a cycle exists; the
    concrete path is reconstructed by walking predecessors inside the
    non-eliminated subgraph.
    """
    node_ids = {
        str(node.get("id"))
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    successors: dict[str, list[str]] = defaultdict(list)
    predecessors: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("type") or "") not in DATA_FLOW_EDGE_TYPES:
            continue
        source = _edge_source(edge)
        target = _edge_target(edge)
        if source not in node_ids or target not in node_ids:
            continue
        successors[source].append(target)
        predecessors[target].append(source)
        indegree[target] += 1

    queue = [node_id for node_id in node_ids if indegree[node_id] == 0]
    pending = set(node_ids)
    while queue:
        node = queue.pop()
        pending.discard(node)
        for target in successors.get(node, ()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if not pending:
        return None

    # Every pending node has at least one predecessor inside `pending`, so the
    # backward walk always proceeds and must revisit a node within len(pending)
    # steps. path[k+1] -> path[k] are forward edges.
    start = min(pending)
    path = [start]
    seen = {start: 0}
    node = start
    while True:
        prev = next((p for p in predecessors.get(node, ()) if p in pending), None)
        if prev is None:
            return None  # defensive: cannot happen for a Kahn leftover set
        if prev in seen:
            segment = path[seen[prev]:]
            return [segment[0], *reversed(segment[1:]), segment[0]]
        seen[prev] = len(path)
        path.append(prev)
        node = prev


def _edge_source(edge: dict[str, Any]) -> Any:
    value = edge_source(edge)
    return str(value) if value is not None else None


def _edge_target(edge: dict[str, Any]) -> Any:
    value = edge_target(edge)
    return str(value) if value is not None else None
