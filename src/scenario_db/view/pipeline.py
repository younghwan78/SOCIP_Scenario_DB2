"""Pipeline graph helpers for view projections."""
from __future__ import annotations

from typing import Any

from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.graph_checks import edge_matches as _edge_matches
from scenario_db.view.buffers import _buffer_detail_items, _size_text

def _node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str | None,
    pipeline_node: dict[str, Any] | None = None,
) -> list[str]:
    if not node_id:
        return []
    config = (getattr(graph.variant, "node_configs", None) or {}).get(node_id) or {}
    details: list[str] = []
    if pipeline_node:
        role = pipeline_node.get("role")
        if role:
            details.append(f"Role: {role}")
    if not isinstance(config, dict) or not config:
        return details

    kind = config.get("kind") or config.get("type")
    if kind:
        details.append(f"Variant config: {kind}")
    mode = config.get("mode")
    if mode:
        details.append(f"Mode: {mode}")
    if kind == "sw_task" or config.get("processor") or config.get("duration_ms") is not None:
        details.append(_sw_task_summary(config))

    input_summary = _port_summary(config.get("inputs"))
    if input_summary:
        details.append("Inputs: " + input_summary)
    output_summary = _port_summary(config.get("outputs"))
    if output_summary:
        details.append("Outputs: " + output_summary)
    return details

def _task_node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node_spec: dict[str, Any],
) -> list[str]:
    details = _node_detail_items(graph, node_id, node_spec)
    if node_spec.get("buffer"):
        details.extend(_buffer_detail_items(graph, str(node_spec["buffer"])))
    return details

def _edge_detail_items(
    graph: CanonicalScenarioGraph,
    edge: dict[str, Any],
    buffer_ref: str | None,
) -> list[str]:
    details: list[str] = []
    source = edge.get("from") or edge.get("source")
    target = edge.get("to") or edge.get("target")
    if source and target:
        details.append(f"Route: {source} -> {target}")
    edge_type = edge.get("type")
    if edge_type:
        details.append(f"Edge type: {edge_type}")
    if buffer_ref:
        details.extend(_buffer_detail_items(graph, buffer_ref))
    return details

def _sw_task_summary(config: dict[str, Any]) -> str:
    bits = [
        config.get("name") or config.get("group") or "SW task",
        config.get("processor"),
        f"{config.get('duration_ms')}ms" if config.get("duration_ms") is not None else None,
    ]
    return "SW task: " + " / ".join(str(bit) for bit in bits if bit)

def _port_summary(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        bits = [
            item.get("port"),
            _size_text(item.get("size")),
            item.get("format"),
            f"{item.get('bitwidth')}b" if item.get("bitwidth") is not None else None,
            item.get("comp"),
        ]
        items.append(" ".join(str(bit) for bit in bits if bit))
    if len(value) > 3:
        items.append(f"+{len(value) - 3} more")
    return "; ".join(items) if items else None

def _sw_layer_for_node(pipeline_node: dict[str, Any]) -> str:
    text = f"{pipeline_node.get('id', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("app", "source", "network", "storage")):
        return "app"
    if any(token in text for token in ("hal", "audio_hal")):
        return "hal"
    if any(token in text for token in ("driver", "v4l2", "drm", "kms", "dsp", "offload", "eis", "m2m_scaler")):
        return "kernel"
    return "framework"

def _stage_for_node(node_id: str | None, pipeline_node: dict[str, Any]) -> str:
    text = f"{node_id or ''} {pipeline_node.get('ip_ref', '')} {pipeline_node.get('role', '')}".lower()
    if any(token in text for token in ("sensor", "csis", "pdp", "csi")):
        return "capture"
    if any(token in text for token in ("mfc", "codec", "enc")):
        return "encode"
    if any(token in text for token in ("dpu", "display", "drm")):
        return "display"
    return "processing"

def _edge_flow_type(edge: dict[str, Any]) -> str:
    flow_type = str(edge.get("type") or "M2M")
    if flow_type in {"OTF", "vOTF", "M2M", "control", "risk"}:
        return flow_type
    lowered = flow_type.lower()
    if lowered == "votf":
        return "vOTF"
    if lowered == "otf":
        return "OTF"
    if lowered == "m2m":
        return "M2M"
    return "M2M"

def _find_pipeline_node(graph: CanonicalScenarioGraph, node_id: str | None) -> dict[str, Any] | None:
    return graph.node_by_id(node_id)

def _find_pipeline_node_by_ip_ref(graph: CanonicalScenarioGraph, ip_ref: str | None) -> dict[str, Any] | None:
    for node in graph.pipeline_nodes:
        if node.get("ip_ref") == ip_ref:
            return node
    return None

def _edges_touching_node(graph: CanonicalScenarioGraph, node_id: str | None) -> list[dict[str, Any]]:
    return [edge for edge in graph.pipeline_edges if edge.get("from") == node_id or edge.get("to") == node_id]

def _is_memory_ip(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> bool:
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    return bool(ip_row and ip_row.category == "memory")

def _pipeline_node_layer(graph: CanonicalScenarioGraph, pipeline_node: dict[str, Any]) -> str:
    explicit = str(pipeline_node.get("layer") or "").lower()
    if explicit in {"app", "framework", "hal", "kernel", "hw", "memory"}:
        return explicit
    node_type = str(pipeline_node.get("node_type") or pipeline_node.get("kind") or "").lower()
    if node_type in {"sw", "task", "cpu"}:
        return _sw_layer_for_node(pipeline_node)
    ip_row = graph.ip_catalog.get(pipeline_node.get("ip_ref") or "")
    if str(getattr(ip_row, "category", "") or "").lower() == "cpu":
        return _sw_layer_for_node(pipeline_node)
    if _is_memory_ip(graph, pipeline_node):
        return "memory"
    return "hw"

def _pipeline_node_type(layer: str) -> str:
    if layer in {"app", "framework", "hal", "kernel"}:
        return "sw"
    if layer == "memory":
        return "buffer"
    return "ip"

def _dma_count_for_node(graph: CanonicalScenarioGraph, node_id: str | None) -> int:
    memory_edges = [edge for edge in _edges_touching_node(graph, node_id) if edge.get("type") == "M2M"]
    return max(1, len(memory_edges))


def _task_edge_removed(edge: dict[str, Any], remove_specs: list[Any]) -> bool:
    return any(isinstance(spec, dict) and _edge_matches(edge, spec) for spec in remove_specs)
