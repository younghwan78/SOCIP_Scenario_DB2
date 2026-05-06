"""Level 0 view projection orchestration.

This module owns the Level 0 architecture/topology assembly flow while the
lower-level data extraction helpers remain in service.py for now. Keeping the
helper surface explicit avoids a broad behavior-changing refactor.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scenario_db.api.schemas.view import EdgeElement, NodeElement, ViewHints, ViewResponse
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.layout import CANVAS_H, CANVAS_W


@dataclass(frozen=True)
class Level0ProjectionDeps:
    sw_stack_nodes: Callable[[CanonicalScenarioGraph], list[NodeElement]]
    architecture_resource_nodes: Callable[
        [CanonicalScenarioGraph, dict[tuple[str, str], int]],
        tuple[list[NodeElement], dict[str, str]],
    ]
    buffer_nodes_from_architecture_edges: Callable[
        [CanonicalScenarioGraph, dict[str, str], dict[tuple[str, str], int]],
        list[NodeElement],
    ]
    architecture_edges: Callable[[CanonicalScenarioGraph, dict[str, str]], list[EdgeElement]]
    inferred_architecture_edges: Callable[[CanonicalScenarioGraph, set[str]], list[EdgeElement]]
    sw_control_edges: Callable[[CanonicalScenarioGraph, dict[str, str], set[str]], list[EdgeElement]]
    risk_edges: Callable[[CanonicalScenarioGraph, dict[str, str]], list[EdgeElement]]
    response: Callable[..., ViewResponse]
    pipeline_ranks: Callable[[CanonicalScenarioGraph], dict[str, int]]
    node_element: Callable[..., NodeElement]
    node_label: Callable[[str | None, dict[str, Any]], str]
    pipeline_node_type: Callable[[str], str]
    pipeline_node_layer: Callable[[CanonicalScenarioGraph, dict[str, Any]], str]
    capability_badges: Callable[[CanonicalScenarioGraph, dict[str, Any]], list[str]]
    operation_summary: Callable[[CanonicalScenarioGraph, str, dict[str, Any]], Any]
    node_detail_items: Callable[[CanonicalScenarioGraph, str | None, dict[str, Any] | None], list[str]]
    stage_for_node: Callable[[str | None, dict[str, Any]], str]
    memory_descriptor: Callable[[CanonicalScenarioGraph, str | None], Any]
    memory_placement: Callable[[CanonicalScenarioGraph, str | None], Any]
    buffer_detail_items: Callable[[CanonicalScenarioGraph, str | None], list[str]]
    safe_id: Callable[[str], str]
    buffer_label: Callable[[str], str]
    topology_edges: Callable[[CanonicalScenarioGraph], list[EdgeElement]]


def project_architecture(
    graph: CanonicalScenarioGraph,
    level: int,
    deps: Level0ProjectionDeps,
) -> ViewResponse:
    nodes: list[NodeElement] = []
    edges: list[EdgeElement] = []
    stage_orders: dict[tuple[str, str], int] = {}

    nodes.extend(deps.sw_stack_nodes(graph))
    arch_nodes, node_map = deps.architecture_resource_nodes(graph, stage_orders)
    nodes.extend(arch_nodes)
    nodes.extend(deps.buffer_nodes_from_architecture_edges(graph, node_map, stage_orders))
    edges.extend(deps.architecture_edges(graph, node_map))
    edges.extend(deps.inferred_architecture_edges(graph, {node.data.id for node in nodes}))
    edges.extend(deps.sw_control_edges(graph, node_map, {node.data.id for node in nodes}))
    edges.extend(deps.risk_edges(graph, node_map))

    return deps.response(
        graph=graph,
        level=level,
        mode="architecture",
        nodes=nodes,
        edges=edges,
        metadata={"canvas_w": CANVAS_W, "canvas_h": CANVAS_H, "layout": "layered-lanes"},
    )


def project_topology(
    graph: CanonicalScenarioGraph,
    level: int,
    deps: Level0ProjectionDeps,
) -> ViewResponse:
    nodes: list[NodeElement] = []
    ranks = deps.pipeline_ranks(graph)

    for pipeline_node in graph.pipeline_nodes:
        node_id = pipeline_node.get("id")
        if not node_id:
            continue
        rank = ranks.get(node_id, len(nodes))
        layer = deps.pipeline_node_layer(graph, pipeline_node)
        nodes.append(
            deps.node_element(
                f"ip-{node_id}",
                deps.node_label(node_id, pipeline_node),
                deps.pipeline_node_type(layer),
                layer,
                430,
                85 + rank * 110,
                ip_ref=pipeline_node.get("ip_ref"),
                capability_badges=deps.capability_badges(graph, pipeline_node),
                active_operations=deps.operation_summary(graph, node_id, pipeline_node),
                detail_items=deps.node_detail_items(graph, node_id, pipeline_node),
                view_hints=ViewHints(lane=layer, stage=deps.stage_for_node(node_id, pipeline_node), order=rank),
            )
        )

    for idx, edge in enumerate(graph.pipeline_edges):
        buffer_ref = edge.get("buffer")
        if not buffer_ref:
            continue
        source_rank = ranks.get(edge.get("from"), idx)
        target_rank = ranks.get(edge.get("to"), source_rank + 1)
        nodes.append(
            deps.node_element(
                f"buf-{deps.safe_id(buffer_ref)}",
                deps.buffer_label(buffer_ref),
                "buffer",
                "memory",
                720,
                85 + ((source_rank + target_rank) / 2) * 110,
                memory=deps.memory_descriptor(graph, buffer_ref),
                placement=deps.memory_placement(graph, buffer_ref),
                detail_items=deps.buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage="processing", order=idx),
            )
        )

    return deps.response(
        graph=graph,
        level=level,
        mode="topology",
        nodes=nodes,
        edges=deps.topology_edges(graph),
        metadata={
            "canvas_w": 980,
            "canvas_h": max(520, 160 + (len(nodes) * 85)),
            "layout": "vertical-topology",
        },
    )
