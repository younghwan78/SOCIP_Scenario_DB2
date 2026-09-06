"""Semantic Level 1 view projection."""
from __future__ import annotations

from typing import Any

from scenario_db.api.schemas.view import (
    EdgeElement,
    NodeElement,
    ViewHints,
    ViewResponse,
)
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.buffers import (
    _buffer_memory_from_spec,
    _buffer_placement_from_spec,
    _reference_sizes,
)
from scenario_db.view.elements import _e, _n
from scenario_db.view.graph_utils import (
    edge_port_pairs as _edge_port_pairs,
    edge_source as _edge_source,
    edge_target as _edge_target,
    safe_id as _safe_id,
)
from scenario_db.view.pipeline import (
    _edge_detail_items,
    _edge_flow_type,
    _pipeline_node_type,
    _stage_for_node,
)
from scenario_db.view.response import build_view_response as _response
from scenario_db.view.semantic_constants import _LEVEL1_HIERARCHY_ORDER
from scenario_db.view.semantics import (
    _explicit_level1_operation_summary,
    _level1_capability_badges,
    _level1_effective_edges,
    _level1_edge_label,
    _level1_group_nodes,
    _level1_inner_group_id,
    _level1_node_detail_items,
    _level1_node_label,
    _level1_node_layer,
    _level1_semantics_for_node,
    _level1_summary_badges,
    _level1_topological_nodes,
    _level1_visible_nodes,
)

def _project_semantic_level1(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    """Project active scenario IP/SW nodes into a semantic Level 1 DAG."""

    raw_nodes = _level1_visible_nodes(graph)
    if not raw_nodes:
        return None

    raw_edges = _level1_effective_edges(graph)
    ordered_nodes = _level1_topological_nodes(raw_nodes, raw_edges)
    semantics = {
        str(node.get("id")): _level1_semantics_for_node(graph, node)
        for node in ordered_nodes
        if node.get("id")
    }

    nodes: list[NodeElement] = []
    nodes.extend(_level1_group_nodes(semantics))

    node_map: dict[str, str] = {}
    for index, pipeline_node in enumerate(ordered_nodes):
        node_id = str(pipeline_node.get("id") or "")
        if not node_id:
            continue
        sem = semantics[node_id]
        view_id = f"ip-{_safe_id(node_id)}"
        node_map[node_id] = view_id
        layer = _level1_node_layer(graph, pipeline_node, sem)
        ops = _explicit_level1_operation_summary(graph, node_id, pipeline_node)
        nodes.append(
            _n(
                view_id,
                _level1_node_label(node_id, pipeline_node),
                _pipeline_node_type(layer),
                layer,
                180 + (_LEVEL1_HIERARCHY_ORDER.get(str(sem["hierarchy_group"]), 99) * 90),
                120 + index * 74,
                parent=_level1_inner_group_id(str(sem["hierarchy_group"]), str(sem["ip_group"])),
                ip_ref=pipeline_node.get("ip_ref"),
                hierarchy_group=sem["hierarchy_group"],
                ip_group=sem["ip_group"],
                dvfs_group=sem.get("dvfs_group"),
                role_hw_name=sem.get("role_hw_name"),
                semantic_source=sem["source"],
                summary_badges=_level1_summary_badges(sem, layer, ops),
                capability_badges=_level1_capability_badges(sem),
                active_operations=ops,
                detail_items=_level1_node_detail_items(graph, node_id, pipeline_node, sem),
                view_hints=ViewHints(
                    lane=layer,
                    stage=_stage_for_node(node_id, pipeline_node),
                    order=index,
                    width=160,
                    height=62,
                ),
            )
        )

    edges: list[EdgeElement] = []
    tokens = _reference_sizes(graph)
    for index, edge in enumerate(raw_edges):
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        view_source = node_map.get(source)
        view_target = node_map.get(target)
        if not view_source or not view_target:
            continue
        buffer_ref = edge.get("buffer")
        buffer_text = str(buffer_ref) if buffer_ref else None
        flow_type = _edge_flow_type(edge)
        edges.append(
            _e(
                str(edge.get("id") or f"l1-sem-{index}"),
                view_source,
                view_target,
                flow_type,
                label=_level1_edge_label(flow_type, buffer_text),
                buffer_ref=buffer_text,
                producer=source,
                consumer=target,
                port_pairs=_edge_port_pairs(edge),
                memory=_buffer_memory_from_spec(graph, buffer_text, tokens) if buffer_text else None,
                placement=_buffer_placement_from_spec(graph, buffer_text) if buffer_text else None,
                detail_items=_edge_detail_items(graph, edge, buffer_text),
            )
        )

    return _response(
        graph=graph,
        level=1,
        mode="level1-ip-detail",
        nodes=nodes,
        edges=edges,
        metadata={
            "canvas_w": 1280,
            "canvas_h": max(860, 220 + len(nodes) * 58),
            "layout": "level1-semantic-ip-dag",
            "active_node_count": len(ordered_nodes),
            "active_edge_count": len(raw_edges),
            "group_count": sum(1 for node in nodes if node.data.layer == "meta" and node.data.type == "submodule"),
        },
    )














































def project_semantic_level1(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    return _project_semantic_level1(graph)
