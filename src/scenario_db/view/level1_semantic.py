"""Semantic Level 1 view projection."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from scenario_db.api.schemas.view import (
    EdgeData,
    EdgeElement,
    NodeData,
    NodeElement,
    OperationSummary,
    ViewHints,
    ViewResponse,
)
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.service import (
    _LEVEL1_HIERARCHY_ORDER,
    _LEVEL1_IP_GROUP_ORDER,
    _buffer_memory_from_spec,
    _buffer_placement_from_spec,
    _e,
    _edge_detail_items,
    _edge_flow_type,
    _edge_source,
    _edge_target,
    _n,
    _node_detail_items,
    _pipeline_node_layer,
    _pipeline_node_type,
    _reference_sizes,
    _response,
    _safe_id,
    _stage_for_node,
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


def _level1_visible_nodes(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    return [node for node in graph.pipeline_nodes if not _level1_is_memory_node(graph, node)]


def _level1_is_memory_node(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> bool:
    text = f"{node.get('id', '')} {node.get('role', '')} {node.get('ip_ref', '')}".lower()
    ip_row = graph.ip_catalog.get(node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower() if ip_row else ""
    return category == "memory" or "llc" in text


def _level1_effective_edges(graph: CanonicalScenarioGraph) -> list[dict[str, Any]]:
    memory_node_ids = {
        str(node.get("id"))
        for node in graph.pipeline_nodes
        if node.get("id") and _level1_is_memory_node(graph, node)
    }
    if not memory_node_ids:
        return list(graph.pipeline_edges)

    outgoing_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in graph.pipeline_edges:
        outgoing_by_source[str(_edge_source(edge) or "")].append(edge)

    collapsed: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any, Any]] = set()
    for edge in graph.pipeline_edges:
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        if source in memory_node_ids:
            continue
        if target not in memory_node_ids:
            _level1_append_edge_once(collapsed, seen, edge)
            continue
        buffer_ref = edge.get("buffer")
        for next_edge in outgoing_by_source.get(target, []):
            consumer = str(_edge_target(next_edge) or "")
            if consumer in memory_node_ids:
                continue
            if buffer_ref and next_edge.get("buffer") and next_edge.get("buffer") != buffer_ref:
                continue
            merged = dict(edge)
            merged["to"] = consumer
            merged.pop("target", None)
            _level1_append_edge_once(collapsed, seen, merged)
    return collapsed


def _level1_append_edge_once(
    edges: list[dict[str, Any]],
    seen: set[tuple[Any, Any, Any, Any]],
    edge: dict[str, Any],
) -> None:
    key = (_edge_source(edge), _edge_target(edge), edge.get("type"), edge.get("buffer"))
    if key in seen:
        return
    seen.add(key)
    edges.append(edge)


def _level1_topological_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    original_order = {str(node.get("id")): index for index, node in enumerate(nodes) if node.get("id")}
    indegree = {node_id: 0 for node_id in by_id}
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        if source not in by_id or target not in by_id:
            continue
        outgoing[source].append(target)
        indegree[target] += 1

    queue = sorted([node_id for node_id, count in indegree.items() if count == 0], key=original_order.get)
    ordered: list[str] = []
    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for target in sorted(outgoing[node_id], key=original_order.get):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
        queue.sort(key=original_order.get)

    if len(ordered) != len(by_id):
        ordered = sorted(by_id, key=original_order.get)
    return [by_id[node_id] for node_id in ordered]


def _level1_group_nodes(semantics: dict[str, dict[str, str | None]]) -> list[NodeElement]:
    hierarchy_groups = sorted(
        {str(sem["hierarchy_group"]) for sem in semantics.values()},
        key=lambda group: (_LEVEL1_HIERARCHY_ORDER.get(group, 99), group),
    )
    nodes: list[NodeElement] = []
    for index, hierarchy in enumerate(hierarchy_groups):
        nodes.append(
            _level1_group_node(
                _level1_outer_group_id(hierarchy),
                hierarchy,
                220 + index * 130,
                80,
                360,
                220,
                hierarchy_group=hierarchy,
                order=_LEVEL1_HIERARCHY_ORDER.get(hierarchy, 99),
            )
        )

    inner_keys = sorted(
        {(str(sem["hierarchy_group"]), str(sem["ip_group"])) for sem in semantics.values()},
        key=lambda item: (
            _LEVEL1_HIERARCHY_ORDER.get(item[0], 99),
            _LEVEL1_IP_GROUP_ORDER.get(item[1], 999),
            item[1],
        ),
    )
    for index, (hierarchy, ip_group) in enumerate(inner_keys):
        nodes.append(
            _level1_group_node(
                _level1_inner_group_id(hierarchy, ip_group),
                ip_group,
                220 + index * 90,
                210,
                260,
                150,
                parent=_level1_outer_group_id(hierarchy),
                hierarchy_group=hierarchy,
                ip_group=ip_group,
                order=_LEVEL1_IP_GROUP_ORDER.get(ip_group, 999),
            )
        )
    return nodes


def _level1_group_node(
    node_id: str,
    label: str,
    x: float,
    y: float,
    width: int,
    height: int,
    *,
    parent: str | None = None,
    hierarchy_group: str | None = None,
    ip_group: str | None = None,
    order: int = 0,
) -> NodeElement:
    return _n(
        node_id,
        label,
        "submodule",
        "meta",
        x,
        y,
        parent=parent,
        hierarchy_group=hierarchy_group,
        ip_group=ip_group,
        semantic_source="level1-semantic-group",
        view_hints=ViewHints(width=width, height=height, emphasis="muted", order=order),
    )


def _level1_semantics_for_node(graph: CanonicalScenarioGraph, node: dict[str, Any]) -> dict[str, str | None]:
    ip_row = graph.ip_catalog.get(node.get("ip_ref") or "")
    category = str(getattr(ip_row, "category", "") or "").lower() if ip_row else ""
    capabilities = getattr(ip_row, "capabilities", None) or {}
    properties = capabilities.get("properties") or {}
    role_entry = _level1_role_mode_entry(node, capabilities)
    role_hw_name = str(role_entry.get("hw_name")) if role_entry and role_entry.get("hw_name") else None
    hierarchy = _level1_normalize_hierarchy_group(properties.get("hierarchy_group") or _level1_hierarchy_from_category(category, node))
    ip_group = _level1_ip_group(node, category, properties, role_hw_name, hierarchy)
    return {
        "hierarchy_group": hierarchy,
        "ip_group": ip_group,
        "dvfs_group": _level1_dvfs_group(graph, node, role_entry),
        "role_hw_name": role_hw_name,
        "source": "hw_role_mode" if role_entry else ("hw_properties" if properties else "category_fallback"),
    }


def _level1_role_mode_entry(node: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any] | None:
    role_modes = ((capabilities.get("sim") or {}).get("role_modes") or {})
    keys = [
        str(node.get("role") or ""),
        str(node.get("id") or ""),
        str(node.get("label") or ""),
    ]
    for key in keys:
        if key in role_modes and isinstance(role_modes[key], dict):
            return role_modes[key]
    lowered = {key.lower(): value for key, value in role_modes.items() if isinstance(value, dict)}
    for key in keys:
        candidate = lowered.get(key.lower())
        if candidate:
            return candidate
    return None


def _level1_hierarchy_from_category(category: str, node: dict[str, Any]) -> str:
    text = f"{node.get('id', '')} {node.get('role', '')} {node.get('ip_ref', '')}".lower()
    if category == "sensor" or "sensor" in text:
        return "Sensor"
    if category == "cpu":
        return "CPU/SW"
    if category in {"compute", "gpu", "npu"}:
        return "Compute"
    if category == "display" or any(token in text for token in ("dpu", "display", "panel")):
        return "Display" if "panel" in text else "DPU"
    if category == "codec" or any(token in text for token in ("mfc", "codec", "encoder", "decoder")):
        return "CODEC"
    if category == "cpu" or "cpu" in text or "task" in text:
        return "CPU/SW"
    if category == "memory":
        return "Memory"
    if category == "camera" or any(token in text for token in ("isp", "csis", "3aa", "byrp", "rgbp", "yuv", "mtnr", "msnr", "mcsc", "gdc", "lme")):
        return "ISP"
    return "Other"


def _level1_normalize_hierarchy_group(value: Any) -> str:
    text = str(value or "").strip()
    aliases = {
        "sensor": "Sensor",
        "isp": "ISP",
        "camera": "ISP",
        "compute": "Compute",
        "codec": "CODEC",
        "display": "Display",
        "dpu": "DPU",
        "gpu": "GPU",
        "npu": "NPU",
        "cpu": "CPU/SW",
        "cpu/sw": "CPU/SW",
        "memory": "Memory",
    }
    return aliases.get(text.lower(), text or "Other")


def _level1_ip_group(
    node: dict[str, Any],
    category: str,
    properties: dict[str, Any],
    role_hw_name: str | None,
    hierarchy: str,
) -> str:
    text = " ".join(str(value or "") for value in (node.get("id"), node.get("label"), node.get("role"), node.get("ip_ref"), role_hw_name)).lower()
    explicit = properties.get("ip_group")
    if category == "cpu" or hierarchy == "CPU/SW":
        return "CPU/SW"
    if explicit and not (hierarchy == "ISP" and explicit == "ISP"):
        return str(explicit)
    for tokens, group in (
        (("csispdp", "csis", "pdp"), "CSIS/PDP"),
        (("3aa", "cstat"), "3AA/CSTAT"),
        (("byrp",), "BYRP"),
        (("rgbp",), "RGBP"),
        (("yuvsc",), "YUVSC"),
        (("mtnr",), "MTNR"),
        (("msnr",), "MSNR"),
        (("yuvp", "yuv-post", "yuv_post"), "YUVP"),
        (("gdc",), "GDC"),
        (("mcsc",), "MCSC"),
        (("lme",), "LME"),
        (("mfc", "codec", "encoder", "decoder"), "MFC"),
        (("dpu", "decon"), "DPU"),
        (("panel",), "Panel"),
        (("gpu",), "GPU"),
        (("npu",), "NPU"),
    ):
        if any(token in text for token in tokens):
            return group
    if explicit and hierarchy == "ISP" and explicit == "ISP":
        return "ISP Core"
    if category == "sensor":
        return "Sensor"
    if hierarchy == "CPU/SW":
        return "CPU/SW"
    return str(explicit or role_hw_name or hierarchy)


def _level1_dvfs_group(
    graph: CanonicalScenarioGraph,
    node: dict[str, Any],
    role_entry: dict[str, Any] | None,
) -> str | None:
    if not role_entry:
        return None
    modes = role_entry.get("modes") or {}
    if not isinstance(modes, dict) or not modes:
        return None
    node_config = (getattr(graph.variant, "node_configs", None) or {}).get(str(node.get("id") or "")) or {}
    requested_mode = node_config.get("mode") if isinstance(node_config, dict) else None
    for key in (requested_mode, "Normal", "normal", next(iter(modes), None)):
        if key is None:
            continue
        mode = modes.get(key)
        if isinstance(mode, dict) and mode.get("dvfs_group"):
            return str(mode["dvfs_group"])
    return None


def _level1_node_layer(graph: CanonicalScenarioGraph, node: dict[str, Any], sem: dict[str, str | None]) -> str:
    if sem["hierarchy_group"] in {"Sensor", "Display"}:
        return "external"
    return _pipeline_node_layer(graph, node)


def _level1_node_label(node_id: str, pipeline_node: dict[str, Any]) -> str:
    return str(pipeline_node.get("label") or node_id).replace("_", " ").replace("-", " ").upper()


def _level1_summary_badges(
    sem: dict[str, str | None],
    layer: str,
    ops: OperationSummary | None,
) -> list[str]:
    badges = [str(sem["hierarchy_group"]), str(sem["ip_group"])]
    if layer in {"app", "framework", "hal", "kernel"}:
        badges.append("<sw>")
    if sem.get("dvfs_group") and sem["dvfs_group"] not in badges:
        badges.append(str(sem["dvfs_group"]))
    if ops:
        if ops.crop:
            badges.append("Crop")
        if ops.scale:
            badges.append("Scale")
        if ops.rotate is not None:
            badges.append("Rotate")
    return badges


def _level1_capability_badges(sem: dict[str, str | None]) -> list[str]:
    badges: list[str] = []
    if sem.get("role_hw_name"):
        badges.append(f"HW:{sem['role_hw_name']}")
    if sem.get("dvfs_group"):
        badges.append(f"DVFS:{sem['dvfs_group']}")
    return badges


def _level1_node_detail_items(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node: dict[str, Any],
    sem: dict[str, str | None],
) -> list[str]:
    details = _node_detail_items(graph, node_id, node)
    details.extend(
        [
            f"Hierarchy: {sem['hierarchy_group']}",
            f"IP block: {sem['ip_group']}",
        ]
    )
    if sem.get("role_hw_name"):
        details.append(f"Role HW: {sem['role_hw_name']}")
    if sem.get("dvfs_group"):
        details.append(f"DVFS group: {sem['dvfs_group']}")
    edges = _level1_effective_edges(graph)
    incoming = [str(edge.get("buffer")) for edge in edges if _edge_target(edge) == node_id and edge.get("buffer")]
    outgoing = [str(edge.get("buffer")) for edge in edges if _edge_source(edge) == node_id and edge.get("buffer")]
    if incoming:
        details.append("Input buffers: " + ", ".join(incoming[:4]))
    if outgoing:
        details.append("Output buffers: " + ", ".join(outgoing[:4]))
    return details


def _explicit_level1_operation_summary(
    graph: CanonicalScenarioGraph,
    node_id: str,
    node: dict[str, Any],
) -> OperationSummary | None:
    config = (getattr(graph.variant, "node_configs", None) or {}).get(node_id) or {}
    raw_ops = config.get("operations") if isinstance(config, dict) else None
    if raw_ops is None and isinstance(node, dict):
        raw_ops = node.get("operations")
    if not isinstance(raw_ops, dict):
        return None
    summary = OperationSummary(
        crop=bool(raw_ops.get("crop")),
        crop_ratio=raw_ops.get("crop_ratio"),
        scale=bool(raw_ops.get("scale")),
        scale_from=raw_ops.get("scale_from"),
        scale_to=raw_ops.get("scale_to"),
        rotate=raw_ops.get("rotate"),
        compose=bool(raw_ops.get("compose", False)),
        colorspace_convert=raw_ops.get("colorspace_convert"),
    )
    if any((summary.crop, summary.scale, summary.rotate is not None, summary.compose, summary.colorspace_convert)):
        return summary
    return None


def _level1_edge_label(flow_type: str, buffer_ref: str | None) -> str:
    if buffer_ref:
        return f"{flow_type} / {buffer_ref}"
    return flow_type


def _level1_outer_group_id(hierarchy_group: str) -> str:
    return f"grp-{_safe_id(hierarchy_group)}"


def _level1_inner_group_id(hierarchy_group: str, ip_group: str) -> str:
    return f"{_level1_outer_group_id(hierarchy_group)}-{_safe_id(ip_group)}"


def project_semantic_level1(graph: CanonicalScenarioGraph) -> ViewResponse | None:
    return _project_semantic_level1(graph)
