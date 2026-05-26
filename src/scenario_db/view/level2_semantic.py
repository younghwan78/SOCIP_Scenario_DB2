"""Semantic Level 2 drilldown projection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scenario_db.api.schemas.view import EdgeElement, NodeElement, ViewHints, ViewResponse
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph
from scenario_db.view.buffers import (
    _buffer_detail_items,
    _buffer_label,
    _buffer_memory_from_spec,
    _buffer_placement_from_spec,
    _reference_sizes,
)
from scenario_db.view.elements import _e, _n
from scenario_db.view.graph_utils import (
    edge_source as _edge_source,
    edge_target as _edge_target,
    safe_id as _safe_id,
)
from scenario_db.view.pipeline import (
    _edge_detail_items,
    _edge_flow_type,
    _find_pipeline_node,
    _find_pipeline_node_by_ip_ref,
)
from scenario_db.view.response import build_view_response as _response
from scenario_db.view.semantic_constants import (
    _LEVEL1_HIERARCHY_ORDER,
    _LEVEL2_ALIAS_GROUPS,
    _LEVEL2_BLOCK_BY_IP_GROUP,
    _LEVEL2_REFERENCE_ALIASES,
    _LEVEL2_REQUIRED_DATA,
)
from scenario_db.view.semantics import (
    _explicit_level1_operation_summary,
    _level1_capability_badges,
    _level1_effective_edges,
    _level1_edge_label,
    _level1_group_node,
    _level1_node_label,
    _level1_semantics_for_node,
    _level1_topological_nodes,
    _level1_visible_nodes,
)


@dataclass
class Level2NodeSpec:
    node: dict[str, Any]
    node_id: str
    ip_ref: str
    ip_row: Any
    graph: CanonicalScenarioGraph
    sem: dict[str, str | None]
    properties: dict[str, Any]
    block_name: str
    functional_modules: list[str]
    module_nodes: list[dict[str, Any]]
    internal_edges: list[dict[str, Any]]
    functional_ids: dict[str, str] = field(default_factory=dict)
    read_ids: list[str] = field(default_factory=list)
    write_ids: list[str] = field(default_factory=list)


def _project_drilldown(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    semantic = _project_semantic_level2(graph, expand)
    if semantic is not None:
        return semantic

    if str(expand or "").strip().lower() in _LEVEL2_REFERENCE_ALIASES:
        raise LookupError(f"Cannot build semantic Level 2 view for legacy alias: {expand}")
    raise LookupError(f"Cannot expand unknown IP node: {expand}")


def _project_semantic_level2(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    target_nodes = _level2_target_nodes(graph, expand)
    if target_nodes is None:
        return None
    if not target_nodes:
        return _level2_unavailable_response(
            graph,
            expand,
            [f"No active pipeline nodes match expand={expand!r}."],
            target_nodes=[],
        )

    specs: list[Level2NodeSpec] = []
    unavailable_reasons: list[str] = []
    for node in target_nodes:
        spec, reason = _level2_node_spec(graph, node)
        if spec is None:
            unavailable_reasons.append(reason)
            continue
        specs.append(spec)

    if not specs:
        return _level2_unavailable_response(
            graph,
            expand,
            unavailable_reasons,
            target_nodes=[str(node.get("id") or "") for node in target_nodes if node.get("id")],
        )

    return _level2_module_response(graph, expand, specs, unavailable_reasons)


def _level2_target_nodes(graph: CanonicalScenarioGraph, expand: str) -> list[dict[str, Any]] | None:
    normalized = str(expand or "").strip().lower()
    if not normalized:
        return []

    direct = _find_pipeline_node(graph, expand) or _find_pipeline_node_by_ip_ref(graph, expand)
    if direct is not None:
        return [direct]

    alias = _LEVEL2_ALIAS_GROUPS.get(normalized)
    if alias is None:
        return None

    nodes: list[dict[str, Any]] = []
    for node in _level1_visible_nodes(graph):
        if _level2_node_matches_alias(graph, node, alias):
            nodes.append(node)
    return _level1_topological_nodes(nodes, _level1_effective_edges(graph)) if nodes else []


def _level2_node_matches_alias(graph: CanonicalScenarioGraph, node: dict[str, Any], alias: str) -> bool:
    sem = _level1_semantics_for_node(graph, node)
    hierarchy = str(sem.get("hierarchy_group") or "")
    ip_group = str(sem.get("ip_group") or "")
    text = f"{node.get('id', '')} {node.get('role', '')} {node.get('ip_ref', '')}".lower()
    if alias == "camera":
        return hierarchy == "ISP"
    if alias == "video":
        return hierarchy == "CODEC" or ip_group in {"MFC", "APV"} or any(token in text for token in ("mfc", "codec"))
    if alias == "display":
        return ip_group == "DPU" or any(token in text for token in ("dpu", "decon"))
    return False


def _level2_node_spec(
    graph: CanonicalScenarioGraph,
    pipeline_node: dict[str, Any],
) -> tuple[Level2NodeSpec | None, str]:
    node_id = str(pipeline_node.get("id") or "")
    ip_ref = str(pipeline_node.get("ip_ref") or "")
    ip_row = graph.ip_catalog.get(ip_ref)
    sem = _level1_semantics_for_node(graph, pipeline_node)
    if ip_row is None:
        return None, f"{node_id} references {ip_ref or 'no ip_ref'}, but the IP catalog row is not loaded."

    capabilities = getattr(ip_row, "capabilities", None) or {}
    properties = capabilities.get("properties") or {}
    hierarchy = getattr(ip_row, "hierarchy", None) or {}
    modules = [item for item in properties.get("modules") or [] if isinstance(item, dict)]
    subblocks = [str(item) for item in properties.get("subblocks") or [] if item]
    hierarchy_submodules = [item for item in hierarchy.get("submodules") or [] if isinstance(item, dict)]
    internal_edges = [item for item in properties.get("internal_edges") or [] if isinstance(item, dict)]
    block_name = _level2_block_name(pipeline_node, sem)

    functional_modules = _level2_functional_modules(
        pipeline_node,
        sem,
        block_name,
        subblocks,
        hierarchy_submodules,
        modules,
    )
    module_nodes = _level2_matching_modules(modules, block_name, functional_modules)

    if not functional_modules and not module_nodes:
        return (
            None,
            (
                f"{node_id} ({ip_ref}) has no Level 2 module declarations. "
                "Add capabilities.properties.modules, capabilities.properties.subblocks, "
                "or hierarchy.submodules to render IP-internal modules."
            ),
        )

    if not functional_modules:
        functional_modules = [block_name]

    return (
        Level2NodeSpec(
            node=pipeline_node,
            node_id=node_id,
            ip_ref=ip_ref,
            ip_row=ip_row,
            graph=graph,
            sem=sem,
            properties=properties,
            block_name=block_name,
            functional_modules=functional_modules,
            module_nodes=module_nodes,
            internal_edges=internal_edges,
        ),
        "",
    )


def _level2_block_name(pipeline_node: dict[str, Any], sem: dict[str, str | None]) -> str:
    ip_group = str(sem.get("ip_group") or "")
    if ip_group in _LEVEL2_BLOCK_BY_IP_GROUP:
        return _LEVEL2_BLOCK_BY_IP_GROUP[ip_group]
    role_hw = str(sem.get("role_hw_name") or "")
    if role_hw:
        return role_hw
    text = f"{pipeline_node.get('id', '')} {pipeline_node.get('role', '')} {pipeline_node.get('ip_ref', '')}".lower()
    for tokens, block in (
        (("csispdp", "pdp"), "CSISPDP"),
        (("csis",), "CSIS"),
        (("3aa", "cstat"), "3AA"),
        (("byrp",), "BYRP"),
        (("rgbp",), "RGBP"),
        (("yuvsc",), "YUVSC"),
        (("mtnr",), "MTNR"),
        (("msnr",), "MSNR"),
        (("yuvp",), "YUVP"),
        (("mcsc",), "MCSC"),
        (("gdc",), "GDC"),
        (("lme",), "LME"),
        (("mfc", "codec"), "MFC"),
        (("dpu", "decon"), "DPU"),
        (("gpu", "sgpu"), "SGPU"),
        (("npu",), "NPU"),
    ):
        if any(token in text for token in tokens):
            return block
    return str(pipeline_node.get("id") or "MODULE").upper()


def _level2_functional_modules(
    pipeline_node: dict[str, Any],
    sem: dict[str, str | None],
    block_name: str,
    subblocks: list[str],
    hierarchy_submodules: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> list[str]:
    if hierarchy_submodules:
        return [
            str(item.get("instance_id") or item.get("ref") or f"sub{index}")
            for index, item in enumerate(hierarchy_submodules)
        ]

    matches = [name for name in subblocks if _level2_norm(name) == _level2_norm(block_name)]
    if matches:
        return matches
    if subblocks and _level2_should_expand_all_subblocks(pipeline_node, sem):
        return subblocks
    if modules:
        return [block_name]
    return []


def _level2_should_expand_all_subblocks(pipeline_node: dict[str, Any], sem: dict[str, str | None]) -> bool:
    ip_group = str(sem.get("ip_group") or "")
    text = f"{pipeline_node.get('id', '')} {pipeline_node.get('role', '')}".lower()
    return ip_group in {"DPU", "ISP Core"} or text in {"isp", "isp0", "dpu"}


def _level2_matching_modules(
    modules: list[dict[str, Any]],
    block_name: str,
    functional_modules: list[str],
) -> list[dict[str, Any]]:
    block_norms = {_level2_norm(block_name), *(_level2_norm(item) for item in functional_modules)}
    matched: list[dict[str, Any]] = []
    for module in modules:
        name = str(module.get("name") or "")
        name_norm = _level2_norm(name)
        if any(name_norm.startswith(block) or block in name_norm for block in block_norms if block):
            matched.append(module)
    return matched


def _level2_module_response(
    graph: CanonicalScenarioGraph,
    expand: str,
    specs: list[Level2NodeSpec],
    omitted_reasons: list[str],
) -> ViewResponse:
    nodes: list[NodeElement] = []
    hierarchy_groups = sorted(
        {str(spec.sem.get("hierarchy_group") or "Other") for spec in specs},
        key=lambda group: (_LEVEL1_HIERARCHY_ORDER.get(group, 99), group),
    )
    for index, hierarchy in enumerate(hierarchy_groups):
        nodes.append(
            _level1_group_node(
                f"grp-l2-{_safe_id(hierarchy)}",
                hierarchy,
                220 + index * 160,
                80,
                420,
                240,
                hierarchy_group=hierarchy,
                order=_LEVEL1_HIERARCHY_ORDER.get(hierarchy, 999),
            )
        )

    for index, spec in enumerate(specs):
        _level2_append_ip_package(nodes, spec, index)

    edges = _level2_module_edges(graph, specs, nodes)
    canvas_h = max(760, 280 + len(specs) * 140 + sum(len(spec.module_nodes) for spec in specs) * 42)
    return _response(
        graph=graph,
        level=2,
        mode=f"drilldown:{expand}",
        nodes=nodes,
        edges=edges,
        metadata={
            "canvas_w": 1280,
            "canvas_h": canvas_h,
            "layout": "level2-module-detail",
            "expand": expand,
            "level2_available": True,
            "target_nodes": [spec.node_id for spec in specs],
            "module_source": "ip_catalog.capabilities.properties",
            "rendered_module_count": sum(len(spec.functional_ids) + len(spec.module_nodes) for spec in specs),
            "omitted_reasons": omitted_reasons,
        },
    )


def _level2_append_ip_package(nodes: list[NodeElement], spec: Level2NodeSpec, index: int) -> None:
    node_id = spec.node_id
    sem = spec.sem
    hierarchy = str(sem.get("hierarchy_group") or "Other")
    ip_group = str(sem.get("ip_group") or spec.block_name)
    package_id = f"l2pkg-{_safe_id(node_id)}"
    nodes.append(
        _n(
            package_id,
            _level1_node_label(node_id, spec.node),
            "submodule",
            "meta",
            220,
            180 + index * 130,
            parent=f"grp-l2-{_safe_id(hierarchy)}",
            ip_ref=spec.ip_ref,
            hierarchy_group=hierarchy,
            ip_group=ip_group,
            role_hw_name=sem.get("role_hw_name"),
            semantic_source="level2-ip-package",
            detail_items=_level2_package_detail_items(spec),
            view_hints=ViewHints(lane="hw", stage="processing", order=index, width=360, height=180),
        )
    )

    order = 0
    for module_name in spec.functional_modules:
        module_id = _level2_functional_id(node_id, module_name)
        spec.functional_ids[_level2_norm(module_name)] = module_id
        nodes.append(
            _n(
                module_id,
                _level2_label(module_name),
                "submodule",
                "hw",
                240 + order * 64,
                320 + index * 130,
                parent=package_id,
                ip_ref=spec.ip_ref,
                hierarchy_group=hierarchy,
                ip_group=ip_group,
                role_hw_name=sem.get("role_hw_name"),
                semantic_source="level2-functional-module",
                module_ref=module_name,
                module_kind="functional",
                module_status="declared",
                summary_badges=[hierarchy, ip_group, "Module"],
                capability_badges=_level1_capability_badges(sem),
                active_operations=_explicit_level1_operation_summary(spec.graph, node_id, spec.node),
                detail_items=_level2_functional_detail_items(spec, module_name),
                view_hints=ViewHints(lane="hw", stage="processing", order=order, width=165, height=62),
            )
        )
        order += 1

    for module in spec.module_nodes:
        module_name = str(module.get("name") or f"module-{order}")
        module_kind = _level2_module_kind(module)
        module_direction = _level2_module_direction(module)
        module_id = _level2_module_id(node_id, module_name)
        if module_direction == "input":
            spec.read_ids.append(module_id)
        elif module_direction == "output":
            spec.write_ids.append(module_id)
        nodes.append(
            _n(
                module_id,
                _level2_label(module_name),
                "submodule",
                "hw",
                240 + order * 64,
                320 + index * 130,
                parent=package_id,
                ip_ref=spec.ip_ref,
                hierarchy_group=hierarchy,
                ip_group=ip_group,
                role_hw_name=sem.get("role_hw_name"),
                semantic_source="level2-io-module",
                module_ref=module_name,
                module_kind=module_kind,
                module_direction=module_direction,
                module_status=_level2_module_status(module),
                summary_badges=[module_kind.upper(), module_direction] if module_direction else [module_kind.upper()],
                capability_badges=_level2_module_capability_badges(module),
                detail_items=_level2_module_detail_items(module, spec),
                view_hints=ViewHints(lane="hw", stage="processing", order=order, width=185, height=64),
            )
        )
        order += 1


def _level2_module_edges(
    graph: CanonicalScenarioGraph,
    specs: list[Level2NodeSpec],
    nodes: list[NodeElement],
) -> list[EdgeElement]:
    spec_by_node = {spec.node_id: spec for spec in specs}
    block_to_functional: dict[str, str] = {}
    for spec in specs:
        for key, module_id in spec.functional_ids.items():
            block_to_functional[key] = module_id
        block_to_functional.setdefault(_level2_norm(spec.block_name), _level2_primary_functional_id(spec))

    tokens = _reference_sizes(graph)
    buffer_ids: dict[str, str] = {}
    edges: list[EdgeElement] = []
    seen: set[tuple[str, str, str, str | None]] = set()

    def ensure_buffer(buffer_ref: str, order: int) -> str:
        buffer_id = f"buf-{_safe_id(buffer_ref)}"
        if buffer_ref in buffer_ids:
            return buffer_ids[buffer_ref]
        nodes.append(
            _n(
                buffer_id,
                _buffer_label(buffer_ref),
                "buffer",
                "memory",
                540 + order * 180,
                620,
                memory=_buffer_memory_from_spec(graph, buffer_ref, tokens),
                placement=_buffer_placement_from_spec(graph, buffer_ref),
                detail_items=_buffer_detail_items(graph, buffer_ref),
                view_hints=ViewHints(lane="memory", stage="processing", order=order, width=235, height=68),
            )
        )
        buffer_ids[buffer_ref] = buffer_id
        return buffer_id

    def add_edge(
        source: str,
        target: str,
        flow_type: str,
        *,
        edge: dict[str, Any] | None = None,
        buffer_ref: str | None = None,
        label: str | None = None,
    ) -> None:
        key = (source, target, flow_type, buffer_ref)
        if key in seen:
            return
        seen.add(key)
        edge_id = f"l2e-{len(edges)}-{_safe_id(source)}-{_safe_id(target)}"
        edges.append(
            _e(
                edge_id,
                source,
                target,
                flow_type,
                label=label or _level1_edge_label(flow_type, buffer_ref),
                buffer_ref=buffer_ref,
                memory=_buffer_memory_from_spec(graph, buffer_ref, tokens) if buffer_ref else None,
                placement=_buffer_placement_from_spec(graph, buffer_ref) if buffer_ref else None,
                detail_items=_edge_detail_items(graph, edge or {}, buffer_ref),
            )
        )

    for spec in specs:
        for edge in spec.internal_edges:
            source_id = block_to_functional.get(_level2_norm(str(_edge_source(edge) or "")))
            target_id = block_to_functional.get(_level2_norm(str(_edge_target(edge) or "")))
            if source_id and target_id:
                add_edge(source_id, target_id, _edge_flow_type(edge), edge=edge)

    for index, edge in enumerate(_level1_effective_edges(graph)):
        source = str(_edge_source(edge) or "")
        target = str(_edge_target(edge) or "")
        source_spec = spec_by_node.get(source)
        target_spec = spec_by_node.get(target)
        if not source_spec and not target_spec:
            continue

        flow_type = _edge_flow_type(edge)
        buffer_ref = str(edge.get("buffer")) if edge.get("buffer") else None
        if buffer_ref:
            buffer_id = ensure_buffer(buffer_ref, index)
            if source_spec:
                add_edge(
                    _level2_source_endpoint(source_spec, flow_type),
                    buffer_id,
                    flow_type,
                    edge=edge,
                    buffer_ref=buffer_ref,
                    label=f"{flow_type} write",
                )
            if target_spec:
                add_edge(
                    buffer_id,
                    _level2_target_endpoint(target_spec, flow_type),
                    flow_type,
                    edge=edge,
                    buffer_ref=buffer_ref,
                    label=f"{flow_type} read",
                )
            continue

        if source_spec and target_spec:
            add_edge(
                _level2_source_endpoint(source_spec, flow_type),
                _level2_target_endpoint(target_spec, flow_type),
                flow_type,
                edge=edge,
            )

    return edges


def _level2_unavailable_response(
    graph: CanonicalScenarioGraph,
    expand: str,
    reasons: list[str],
    *,
    target_nodes: list[str],
) -> ViewResponse:
    clean_reasons = [reason for reason in reasons if reason] or [f"No Level 2 module data is available for {expand}."]
    return _response(
        graph=graph,
        level=2,
        mode=f"drilldown:{expand}",
        nodes=[],
        edges=[],
        metadata={
            "canvas_w": 980,
            "canvas_h": 360,
            "layout": "level2-unavailable",
            "expand": expand,
            "level2_available": False,
            "target_nodes": target_nodes,
            "unavailable_reasons": clean_reasons,
            "required_data": _LEVEL2_REQUIRED_DATA,
        },
    )


def _level2_primary_functional_id(spec: Level2NodeSpec) -> str:
    block_id = spec.functional_ids.get(_level2_norm(spec.block_name))
    if block_id:
        return block_id
    if spec.functional_ids:
        return next(iter(spec.functional_ids.values()))
    return f"mod-{_safe_id(spec.node_id)}-{_safe_id(spec.block_name)}"


def _level2_source_endpoint(spec: Level2NodeSpec, flow_type: str) -> str:
    if flow_type == "M2M" and spec.write_ids:
        return spec.write_ids[0]
    return _level2_primary_functional_id(spec)


def _level2_target_endpoint(spec: Level2NodeSpec, flow_type: str) -> str:
    if flow_type == "M2M" and spec.read_ids:
        return spec.read_ids[0]
    return _level2_primary_functional_id(spec)


def _level2_functional_id(node_id: str, module_name: str) -> str:
    return f"mod-{_safe_id(node_id)}-{_safe_id(module_name)}"


def _level2_module_id(node_id: str, module_name: str) -> str:
    return f"mod-{_safe_id(node_id)}-{_safe_id(module_name)}"


def _level2_module_kind(module: dict[str, Any]) -> str:
    module_type = str(module.get("type") or "").lower()
    direction = str(module.get("direction") or "").lower()
    name = str(module.get("name") or "").lower()
    if direction == "read" or "rdma" in name:
        return "rdma"
    if direction == "write" or "wdma" in name:
        return "wdma"
    if "cin" in module_type or "cin" in name:
        return "cin"
    if "cout" in module_type or "cout" in name:
        return "cout"
    if module_type == "dma" or "dma" in name:
        return "dma"
    return module_type or "module"


def _level2_module_direction(module: dict[str, Any]) -> str | None:
    direction = str(module.get("direction") or "").lower()
    if direction == "read":
        return "input"
    if direction == "write":
        return "output"
    if direction in {"input", "output"}:
        return direction
    return None


def _level2_module_status(module: dict[str, Any]) -> str:
    if module.get("enabled") is False:
        return "disabled"
    return str(module.get("status") or "declared")


def _level2_package_detail_items(spec: Level2NodeSpec) -> list[str]:
    details = [
        f"IP: {spec.ip_ref}",
        f"Hierarchy: {spec.sem.get('hierarchy_group')}",
        f"IP block: {spec.sem.get('ip_group')}",
        f"Functional blocks: {', '.join(spec.functional_modules)}",
    ]
    if spec.module_nodes:
        details.append("I/O modules: " + ", ".join(str(module.get("name")) for module in spec.module_nodes))
    return details


def _level2_functional_detail_items(spec: Level2NodeSpec, module_name: str) -> list[str]:
    details = [
        f"Functional module: {module_name}",
        f"Pipeline node: {spec.node_id}",
        f"IP catalog: {spec.ip_ref}",
    ]
    pipeline = spec.properties.get("pipeline_description")
    if pipeline:
        details.append("Pipeline: " + " ".join(str(pipeline).split()))
    return details


def _level2_module_capability_badges(module: dict[str, Any]) -> list[str]:
    badges: list[str] = []
    max_bw = module.get("max_bandwidth")
    if max_bw is not None:
        badges.append(f"MaxBW:{_level2_bandwidth_label(max_bw)}")
    compressions = module.get("supported_compressions") or []
    if compressions:
        badges.append(f"Comp:{len(compressions)}")
    return badges


def _level2_module_detail_items(module: dict[str, Any], spec: Level2NodeSpec) -> list[str]:
    details = [
        f"Module: {module.get('name')}",
        f"Kind: {_level2_module_kind(module)}",
        f"Pipeline node: {spec.node_id}",
    ]
    direction = _level2_module_direction(module)
    if direction:
        details.append(f"Direction: {direction}")
    if module.get("role"):
        details.append(f"Role: {module['role']}")
    if module.get("max_bandwidth") is not None:
        details.append(f"Max bandwidth: {_level2_bandwidth_label(module['max_bandwidth'])}")
    compressions = module.get("supported_compressions") or []
    if compressions:
        details.append("Supported compression: " + ", ".join(str(item) for item in compressions))
    return details


def _level2_bandwidth_label(value: Any) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric >= 1_000_000_000:
        return f"{numeric / 1_000_000_000:g}GB/s"
    if numeric >= 1_000_000:
        return f"{numeric / 1_000_000:g}MB/s"
    return f"{numeric:g}B/s"


def _level2_label(value: Any) -> str:
    return str(value).replace("_", " ").replace(".", " ")


def _level2_norm(value: Any) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

def project_drilldown(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse:
    return _project_drilldown(graph, expand)


def project_semantic_level2(graph: CanonicalScenarioGraph, expand: str) -> ViewResponse | None:
    return _project_semantic_level2(graph, expand)
