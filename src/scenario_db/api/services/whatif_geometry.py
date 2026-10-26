"""Declared geometry constraints and port-aware propagation for detached experiments.

Missing capabilities are unknown, not an implicit hardware crop/scaler. Numeric
bounds only certify the declared model range; source status remains visible.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type


def node_sim(graph, node_id: str) -> dict:
    cfg = (graph.variant.node_configs or {}).get(node_id) or {}
    value = cfg.get("sim") or {}
    return value if isinstance(value, dict) else {}


def ip_sim(graph, node_id: str) -> dict:
    node = next((n for n in graph.pipeline_nodes if str(n.get("id")) == node_id), {})
    row = graph.ip_catalog.get(str(node.get("ip_ref") or ""))
    caps = getattr(row, "capabilities", None) or {}
    value = caps.get("sim") or {}
    return value if isinstance(value, dict) else {}


def evidence(sim: dict, item: dict | None = None) -> dict[str, Any]:
    item = item or {}
    source = item.get("source") or sim.get("source") or "undeclared"
    note = item.get("note") or sim.get("source_note") or ""
    status = item.get("evidence_status") or item.get("status")
    if not status:
        text = f"{source} {note}".lower()
        status = "synthetic" if "synthetic" in text else "borrowed" if "borrowed" in text else "unverified"
    return {"status": status, "source": source, "note": note}


def geometry_for_node(graph, node_id: str) -> dict | None:
    sim = ip_sim(graph, node_id)
    geometry = sim.get("geometry")
    if not isinstance(geometry, dict):
        return None
    raw = geometry.get("operations")
    if not isinstance(raw, dict):
        return None
    operations = {key: dict(value) for key, value in raw.items()
                  if key in {"crop", "scale"} and isinstance(value, dict) and value.get("supported", True)}
    if not operations:
        return None
    default = geometry.get("default_operation") or next(iter(operations))
    if default not in operations:
        return None
    return {"operations": list(operations), "default_operation": default,
            "capabilities": operations, "evidence": evidence(sim, geometry),
            "limits_complete": geometry.get("limits_complete") is True}


def _pair(value: Any, default: tuple[int, int]) -> tuple[int, int]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(
            isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in value):
        raise ValueError("geometry catalog pairs must contain two positive integers")
    return value[0], value[1]


def validate_geometry(graph, node_id: str, data: dict, old: tuple[int, int]) -> tuple[str, str | None, dict]:
    geometry = geometry_for_node(graph, node_id)
    if geometry is None:
        raise ValueError(f"{node_id}: crop/scale capability is not declared")
    operation = data.get("operation") or geometry["default_operation"]
    if operation not in geometry["operations"]:
        raise ValueError(f"{node_id}: {operation} is not supported by the declared geometry capability")
    cap = geometry["capabilities"][operation]
    new = (data["width"], data["height"])
    low, high = _pair(cap.get("min_size"), (16, 16)), _pair(cap.get("max_size"), (16384, 16384))
    alignment = _pair(cap.get("alignment"), (1, 1))
    if any(not low[i] <= new[i] <= high[i] for i in (0, 1)):
        raise ValueError(f"{node_id}: output size is outside the declared {low}..{high} range")
    if any(new[i] % alignment[i] for i in (0, 1)):
        raise ValueError(f"{node_id}: output size requires {alignment[0]}x{alignment[1]} alignment")
    if any(new[i] > old[i] for i in (0, 1)):
        raise ValueError(f"{node_id}: crop/downscale must not exceed the current {old[0]}x{old[1]}")
    if operation == "crop":
        offsets = (data.get("x") or 0, data.get("y") or 0)
        offset_alignment = _pair(cap.get("offset_alignment"), alignment)
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in offsets):
            raise ValueError("crop offsets must be nonnegative integers")
        if any(offsets[i] % offset_alignment[i] for i in (0, 1)):
            raise ValueError(f"{node_id}: crop offset requires {offset_alignment} alignment")
        if any(offsets[i] + new[i] > old[i] for i in (0, 1)):
            raise ValueError(f"{node_id}: crop ROI exceeds input size")
    elif data.get("x") is not None or data.get("y") is not None:
        raise ValueError("crop offsets are not allowed for scaling")
    ratio = cap.get("max_downscale")
    if ratio is not None:
        if isinstance(ratio, bool) or not isinstance(ratio, (float, int)) or not math.isfinite(ratio) or ratio < 1:
            raise ValueError("invalid max_downscale in geometry catalog")
        if any(old[i] / new[i] > ratio for i in (0, 1)):
            raise ValueError(f"{node_id}: scale ratio exceeds declared {ratio:g}:1 limit")
    formats = cap.get("formats") or []
    fmt = str(node_sim(graph, node_id).get("format") or "").upper()
    if formats and (not fmt or fmt not in {str(v).upper() for v in formats}):
        raise ValueError(f"{node_id}: input format {fmt or 'unknown'} is outside declared geometry formats")
    ports = cap.get("ports") or []
    port = data.get("port")
    if port is None and len(ports) == 1:
        port = ports[0]
    if ports and port not in ports:
        raise ValueError(f"{node_id}: select a declared output port ({', '.join(ports)})")
    if not ports and port is not None:
        raise ValueError(f"{node_id}: output port is not declared")
    return operation, port, geometry


def geometry_path(graph, start: str, size: tuple[int, int], port: str | None = None) -> tuple[list[str], list[str]]:
    """Follow the selected source port, stopping at explicit fixed transforms.

    Edges can opt out with geometry.propagate=false or relation=fixed. Authored
    output sizes remain fixed even when numerically equal to the old input size.
    """
    nodes = {str(n.get("id")): n for n in graph.pipeline_nodes}
    outgoing: dict[str, list[dict]] = {}
    for edge in graph.pipeline_edges:
        if edge_type(edge) == "CONTROL":
            continue
        relation = edge.get("geometry") or {}
        if relation.get("propagate") is False or relation.get("relation") == "fixed":
            continue
        outgoing.setdefault(str(edge_source(edge)), []).append(edge)
    pending = deque([(start, True)])
    seen = {start}
    affected, buffers = [], set()
    while pending:
        node_id, first = pending.popleft()
        for edge in outgoing.get(node_id, []):
            if first and port:
                pairs = edge.get("port_pairs") or []
                if not any(p.get("src") == port for p in pairs):
                    continue
            target = str(edge_target(edge))
            sim = node_sim(graph, target)
            if target not in nodes or (sim.get("width"), sim.get("height")) != size:
                continue
            if edge.get("buffer"):
                buffers.add(str(edge["buffer"]))
            if target in seen:
                continue
            seen.add(target)
            affected.append(target)
            # An authored transform terminates inherited geometry at its output.
            fixed_output = any(sim.get(key) is not None for key in (
                "output_width", "width_out", "output_size", "scale_size", "target_size", "scale", "crop"))
            if not fixed_output:
                pending.append((target, False))
    return affected, sorted(buffers)


def mode_compatibility(graph, node_id: str, params: dict, fps: float | None = None) -> tuple[bool | None, str | None]:
    requirements = params.get("requires")
    if not isinstance(requirements, dict) or not requirements:
        return None, "지원 조건 미선언 — 가정 비교이며 하드웨어 호환성 미검증"
    sim = node_sim(graph, node_id)
    size = (sim.get("width"), sim.get("height"))
    if any(not isinstance(v, int) or v <= 0 for v in size):
        return False, "mode 입력 크기를 확인할 수 없음"
    for name, compare in (("min_size", lambda a, b: a < b), ("max_size", lambda a, b: a > b)):
        if name in requirements:
            bounds = _pair(requirements[name], (16, 16))
            if any(compare(size[i], bounds[i]) for i in (0, 1)):
                return False, f"mode {name}={bounds} 조건 위반"
    if requirements.get("sizes") and list(size) not in requirements["sizes"]:
        return False, f"mode 지원 크기 {requirements['sizes']} 조건 위반"
    formats = requirements.get("formats") or []
    if formats and str(sim.get("format") or "").upper() not in {str(f).upper() for f in formats}:
        return False, "mode 입력 format 조건 위반"
    fps = fps or (graph.variant.design_conditions or {}).get("fps")
    if requirements.get("max_fps") is not None and (fps is None or fps > requirements["max_fps"]):
        return False, f"mode 최대 FPS {requirements['max_fps']} 조건 위반"
    features = requirements.get("features") or {}
    for key, value in features.items():
        if (graph.variant.design_conditions or {}).get(key) != value:
            return False, f"mode 기능 조건 {key}={value} 필요"
    return True, None
