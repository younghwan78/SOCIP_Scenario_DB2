"""Reversible What-if conditions over an effective graph — SoC-agnostic and extensible.

Every condition type is a registered ``ChangeKind`` (target name, shape, selector, bounds, label,
``discover`` = which instances exist in this variant, ``apply`` = how it rewrites a detached copy).
The API schema, the target listing, the parser and the UI editor all read this one registry, so a
new condition type is added here only. Nothing is keyed by SoC: availability comes from the
variant's own data (size_profile anchors, node_configs surfaces/params, IP catalog categories,
resolved workloads), so any project whose Timing Budget evaluates can use What-if.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.readiness import check_simulation_readiness
from scenario_db.sim.shape_propagation import _size_tuple, propagate_shapes
from scenario_db.sim.soc_profiles import _PROFILES, profile_for_graph

# ---------------------------------------------------------------- registry


@dataclass(frozen=True)
class ChangeKind:
    target: str
    label: str
    shape: str                       # "size" (width/height) | "value" | "level" (DVFS OPP level) | "choice" (option id)
    selector: str | None = None      # field naming the instance: anchor_id / node_id / stream_id / domain / buffer_id / param
    selector_optional: bool = False  # e.g. output_size resolves the single output itself
    needs_param: bool = False
    unit: str = ""
    max_value: float | None = None
    description: str = ""
    discover: Callable[[dict], list[dict]] = field(default=lambda targets: [], repr=False)
    apply: Callable[["_Apply", dict], tuple] | None = field(default=None, repr=False)
    group: str = "other"             # UI lever palette: sensor / size / temporal / clock / mode / compression / other
    order: int = 50                  # application order: sensor (10) -> power option (20) -> chain size (30) -> rest
    iq: str | None = None            # "required" = adoption needs image-quality evaluation
    value_optional: bool = False     # "choice" kinds that accept an optional numeric ``value`` (e.g. compression ratio)

    def meta(self, targets: dict) -> dict:
        return {"target": self.target, "label": self.label, "shape": self.shape, "selector": self.selector,
                "selector_optional": self.selector_optional, "needs_param": self.needs_param, "unit": self.unit,
                "max_value": self.max_value, "description": self.description, "group": self.group, "iq": self.iq,
                "value_optional": self.value_optional, "choices": self.discover(targets)}


CHANGE_KINDS: dict[str, ChangeKind] = {}


def register(kind: ChangeKind) -> ChangeKind:
    CHANGE_KINDS[kind.target] = kind
    return kind


# Node-config parameters a condition may set directly (flat or sim block).
# key -> (label, unit, max, modeled). Only keys present in the variant are listed; only ``modeled`` keys
# (read by the Timing Budget power/clock model) are offered as conditions — the rest are reported as
# outside the model instead of producing a no-op comparison. Flip ``modeled`` when the engine consumes a key.
NODE_PARAMS: dict[str, tuple[str, str, float, bool]] = {
    "refresh_hz": ("주사율", "Hz", 240.0, False),   # panel/DPU driver path, outside the modeled subtotal
}


@dataclass
class _Apply:
    candidate: Any
    variant: Any
    config: Any
    targets: dict
    seen: set = field(default_factory=set)
    notes: list = field(default_factory=list)


def _buffers(graph):
    overrides = graph.variant.buffer_overrides or {}
    return {key: {**(value or {}), **(overrides.get(key) or {})}
            for key, value in ((graph.scenario.pipeline or {}).get("buffers") or {}).items()}


def _category(graph, node: dict) -> str | None:
    ip = graph.ip_catalog.get(str(node.get("ip_ref") or ""))
    return str(ip.category) if ip is not None and getattr(ip, "category", None) else None


def _anchor_role(graph, anchor_id: str, buffers: dict, nodes_by_id: dict) -> str | None:
    """record / preview from the IP category consuming the anchor's surface, name tokens as fallback."""
    refs = {key for key, b in buffers.items() if b.get("size_ref") == anchor_id}
    consumers = {str(edge_target(e)) for e in graph.pipeline_edges if e.get("buffer") in refs}
    cats = {_category(graph, nodes_by_id[n]) for n in consumers if n in nodes_by_id}
    if "codec" in cats:
        return "record"
    if "display" in cats:
        return "preview"
    low = anchor_id.lower()
    if any(t in low for t in ("record", "video_out", "enc")):
        return "record"
    if any(t in low for t in ("preview", "disp")):
        return "preview"
    return None


def _walk_sizes(block: Any, path: str, out: list[tuple[tuple[int, int], str]]) -> None:
    """(w, h) surfaces in a node config: width/height, w/h, *_width/*_height, 2-int ``src`` lists."""
    if isinstance(block, dict):
        for wk, hk in (("width", "height"), ("w", "h"), ("output_width", "output_height"), ("width_out", "height_out")):
            w, h = block.get(wk), block.get(hk)
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                out.append(((w, h), f"{path}.{wk}"))
        for key in ("size", "output_size", "scale_size", "target_size"):
            if isinstance(block.get(key), str) and _size_tuple(block[key]) != (0, 0):
                out.append((_size_tuple(block[key]), f"{path}.{key}"))
        src = block.get("src")
        if isinstance(src, list) and len(src) == 2 and all(isinstance(v, int) for v in src):
            out.append(((src[0], src[1]), f"{path}.src"))
        for key, value in block.items():
            if key in ("dst",) or key.startswith("panel"):
                continue          # panel geometry is the display, not the stream
            if isinstance(value, (dict, list)):
                _walk_sizes(value, f"{path}.{key}", out)
    elif isinstance(block, list):
        for i, item in enumerate(block):
            label = item.get("name") if isinstance(item, dict) and item.get("name") else str(i)
            _walk_sizes(item, f"{path}[{label}]", out)


def _replace_sizes(block: Any, old: tuple[int, int], new: tuple[int, int]) -> int:
    count = 0
    if isinstance(block, dict):
        for wk, hk in (("width", "height"), ("w", "h"), ("output_width", "output_height"), ("width_out", "height_out")):
            if (block.get(wk), block.get(hk)) == old:
                block[wk], block[hk] = new
                count += 1
        for key in ("size", "output_size", "scale_size", "target_size"):
            if isinstance(block.get(key), str) and _size_tuple(block[key]) == old:
                block[key] = f"{new[0]}x{new[1]}"
                count += 1
        if isinstance(block.get("src"), list) and tuple(block["src"]) == old:
            block["src"] = [new[0], new[1]]
            count += 1
        for key, value in block.items():
            if key in ("dst",) or key.startswith("panel"):
                continue
            if isinstance(value, (dict, list)):
                count += _replace_sizes(value, old, new)
    elif isinstance(block, list):
        for item in block:
            count += _replace_sizes(item, old, new)
    return count


def _streams(graph) -> list[dict]:
    """Surfaces named by size in node configs, grouped by size (scenarios without size_profile anchors)."""
    from scenario_db.sim.workloads import design_size_for_graph
    found: list[tuple[tuple[int, int], str]] = []
    for node_id, cfg in (graph.variant.node_configs or {}).items():
        _walk_sizes(cfg or {}, node_id, found)
    design = design_size_for_graph(graph)
    groups: dict[tuple[int, int], list[str]] = {}
    for size, where in found:
        groups.setdefault(size, []).append(where)
    if design != (0, 0):
        groups.setdefault(design, [])
    rows = [{"id": f"{w}x{h}", "size": [w, h], "where": where, "primary": (w, h) == design}
            for (w, h), where in sorted(groups.items(), key=lambda kv: (-(kv[0] == design), -kv[0][0] * kv[0][1]))]
    return rows


def _node_params(graph) -> list[dict]:
    rows = []
    for node_id, cfg in (graph.variant.node_configs or {}).items():
        for block in (cfg or {}, (cfg or {}).get("sim") or {}):
            for key, (label, unit, _max, modeled) in NODE_PARAMS.items():
                value = block.get(key) if isinstance(block, dict) else None
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 \
                        and not any(r["node_id"] == node_id and r["param"] == key for r in rows):
                    rows.append({"node_id": node_id, "param": key, "label": label, "unit": unit, "value": float(value),
                                 "modeled": modeled})
    return rows


def _capability(graph) -> dict:
    soc = getattr(getattr(graph, "soc", None), "id", None) or (
        ((getattr(graph.project, "metadata_", None) or {}).get("soc_ref")
         or (getattr(graph.project, "globals_", None) or {}).get("soc_ref")) if graph.project is not None else None)
    try:
        ready = check_simulation_readiness(graph)
    except Exception as exc:  # readiness is advisory; the timing run decides
        ready = {"status": "unknown", "errors": [{"code": "READINESS_FAILED", "message": str(exc)}], "warnings": []}
    notes = []
    if soc and soc not in _PROFILES:
        notes.append(f"{soc}: SoC 전용 DVFS group 정책이 없어 기본 정책을 사용합니다")
    unmodeled = sorted({i.get("node_id") for i in ready.get("errors", []) if i.get("code") == "MISSING_PPC" and i.get("node_id")})
    if unmodeled:
        notes.append("clock 모델이 없는 노드(조건 대상 제외, 전력은 부분 모델): " + ", ".join(unmodeled))
    return {"soc_ref": soc, "soc_profile": profile_for_graph(graph).soc_id if soc in _PROFILES else "generic",
            "readiness": ready.get("status"), "notes": notes}


def whatif_targets(graph, config=None, domains: list[dict] | None = None) -> dict[str, Any]:
    """Condition targets of a variant. ``domains`` (DVFS domains resolved by a baseline Timing Budget run:
    current level + ladder) is supplied by the service; without it no DVFS level condition is offered."""
    anchors = dict((graph.scenario.size_profile or {}).get("anchors") or {})
    anchors.update(graph.variant.size_overrides or {})
    buffers = _buffers(graph)
    nodes_by_id = {str(n.get("id")): n for n in graph.pipeline_nodes}
    used_buffers = {str(e.get("buffer")) for e in graph.pipeline_edges if e.get("buffer")}
    used_refs = {str(b.get("size_ref")) for key, b in buffers.items()
                 if key in used_buffers and b.get("size_ref")}
    inputs = build_simulation_inputs(graph, config)
    workloads = {w.node_id: w for w in inputs.workloads}
    shapes = propagate_shapes(graph)
    rows = []
    for key, value in sorted(anchors.items()):
        role = _anchor_role(graph, key, buffers, nodes_by_id)
        kind = "sensor" if "sensor" in key.lower() else "output" if role or any(
            token in key.lower() for token in ("record_out", "preview_out", "video_out", "output")) else "intermediate"
        width, height = _size_tuple(value)
        if not width or not height or (key not in used_refs and kind != "sensor"):
            continue
        rows.append({"id": key, "size": [width, height], "kind": kind, "role": role if kind == "output" else None,
                     "supported": kind != "sensor" and key in used_refs})
    nodes = []
    for node in graph.pipeline_nodes:
        node_id = str(node.get("id") or "")
        workload = workloads.get(node_id)
        if workload is None:
            continue
        shape = shapes.node(node_id)
        port_sizes = {(p.width, p.height) for p in inputs.port_transfers if p.node_id == node_id and p.width and p.height}
        attached_refs = {str(buffers.get(e.get("buffer"), {}).get("size_ref"))
                         for e in graph.pipeline_edges
                         if node_id in {str(edge_source(e)), str(edge_target(e))}
                         and buffers.get(e.get("buffer"), {}).get("size_ref")}
        size_anchors = [r["id"] for r in rows if r["id"] in attached_refs and r["supported"]
                        and r["size"] == [workload.width, workload.height]]
        # A node boundary must correspond to one named surface. RT OTF chains and
        # multi-output scalers cannot be resized safely by a single node field.
        size_supported = len(port_sizes) <= 1 and len(size_anchors) == 1 and len(attached_refs) == 1
        ip_ref = str(node.get("ip_ref") or "")
        stem = ip_ref[3:].split("-")[0] if ip_ref.startswith("ip-") else ""
        nodes.append({"id": node_id, "label": node.get("label") or node_id, "ip": stem or None,
                      "hw_name": workload.hw_name, "category": _category(graph, node),
                      "size": [workload.width, workload.height], "size_supported": size_supported,
                      "size_anchor_id": size_anchors[0] if size_supported else None,
                      "clock_supported": workload.sim_params.ppc > 0,
                      "input_size": [shape.input.width, shape.input.height] if shape else None})
    fps = (config.fps if config is not None and getattr(config, "fps", None) else None) \
        or (graph.variant.design_conditions or {}).get("fps")
    out = {"anchors": rows, "nodes": nodes, "fps": float(fps) if fps else None,
           "output_targets": [r["id"] for r in rows if r["kind"] == "output" and r["supported"]],
           # streams only where the scenario has no size anchors (non-camera: playback, call, game…)
           "streams": [] if rows else _streams(graph),
           "params": _node_params(graph),
           "domains": list(domains or []),
           "capability": _capability(graph)}
    from scenario_db.api.services.whatif_levers import lever_targets
    out.update(lever_targets(graph, out["fps"]))
    kinds = [k.meta(out) for k in CHANGE_KINDS.values()]
    out["change_kinds"] = [k for k in kinds if k["choices"] or k["target"] == "fps" and out["fps"]]
    out["supported_changes"] = [k["target"] for k in out["change_kinds"]]
    out["limitations"] = ["Sensor swap keeps the authored pipeline (same IPs / formats); readout timing and size follow the catalog mode",
                          "Crop / downscale / L0 skip / lossy compression / IP mode need image-quality evaluation before adoption",
                          "History interval lowers previous-frame DMA traffic only; temporal-filter IP core work stays per frame",
                          "SW per-frame runtime and bitstream bitrate stay fixed unless modeled by the existing engine",
                          "Node clock values are manual lower bounds; DVFS/domain constraints may select a higher clock",
                          "FPS changes are hypothetical cadence; sensor catalog FPS support is not validated",
                          "Measured replay/projection cannot be extrapolated", "IQ and hardware wiring are not validated",
                          *out["capability"]["notes"]]
    return out


def _replace_dimensions(block: dict, old: tuple[int, int], new: tuple[int, int]) -> None:
    if (block.get("width"), block.get("height")) == old:
        block["width"], block["height"] = new
    if (block.get("w"), block.get("h")) == old:
        block["w"], block["h"] = new
    _replace_output_dimensions(block, old, new)
    for key in ("size", "output_size", "scale_size", "target_size"):
        if _size_tuple(block.get(key)) == old:
            block[key] = f"{new[0]}x{new[1]}"
    for key in ("crop", "scale"):
        if isinstance(block.get(key), dict):
            _replace_dimensions(block[key], old, new)


def _replace_output_dimensions(block: dict, old: tuple[int, int], new: tuple[int, int]) -> None:
    for width, height in (("output_width", "output_height"), ("width_out", "height_out")):
        if (block.get(width), block.get(height)) == old:
            block[width], block[height] = new
    for key in ("output_size", "scale_size", "target_size"):
        if _size_tuple(block.get(key)) == old:
            block[key] = f"{new[0]}x{new[1]}"
    for key in ("crop", "scale"):
        transform = block.get(key)
        if isinstance(transform, dict):
            if (transform.get("width"), transform.get("height")) == old:
                transform["width"], transform["height"] = new
            if (transform.get("w"), transform.get("h")) == old:
                transform["w"], transform["h"] = new


def _anchor_size(graph, anchor_id: str, new: tuple[int, int], targets) -> None:
    target = next((r for r in targets["anchors"] if r["id"] == anchor_id), None)
    if target is None or not target["supported"]:
        raise ValueError(f"unsupported size anchor: {anchor_id}; sensor changes require catalog selection")
    old = tuple(target["size"])
    graph.variant.size_overrides[anchor_id] = f"{new[0]}x{new[1]}"
    buffers = _buffers(graph)
    refs = {key for key, b in buffers.items() if b.get("size_ref") == anchor_id}
    if any(_size_tuple(buffers[key].get("size")) not in {(0, 0), old} for key in refs):
        raise ValueError("size anchor has conflicting explicit buffer sizes; choose a reviewed surface condition")
    touched_edges = [e for e in graph.pipeline_edges if e.get("buffer") in refs]
    touched_nodes = {str(edge_source(e)) for e in touched_edges} | {str(edge_target(e)) for e in touched_edges}
    for buffer_id in refs:
        override = graph.variant.buffer_overrides.setdefault(buffer_id, {})
        # An explicit size is authoritative over size_ref: update it as part of this anchor condition.
        override["size"] = f"{new[0]}x{new[1]}"
    for node_id in touched_nodes:
        sim = graph.variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})
        incoming = [e for e in graph.pipeline_edges if str(edge_target(e)) == node_id and edge_type(e) != "CONTROL"]
        input_refs = {buffers.get(e.get("buffer"), {}).get("size_ref") for e in incoming}
        # Preserve upstream sensor/scaler processing. Only a consumer whose input is this anchor changes workload.
        if input_refs == {anchor_id}:
            _replace_dimensions(sim, old, new)
        outgoing_refs = {buffers.get(e.get("buffer"), {}).get("size_ref") for e in graph.pipeline_edges
                         if str(edge_source(e)) == node_id and e.get("buffer")}
        if outgoing_refs == {anchor_id}:
            _replace_output_dimensions(sim, old, new)
        for edge in touched_edges:
            source = str(edge_source(edge)) == node_id
            key = "outputs" if source else "inputs"
            ports = {str(pair.get("src" if source else "dst")) for pair in edge.get("port_pairs") or []}
            for port in sim.get(key) or []:
                port_id = str(port.get("port") or port.get("name") or "")
                if port_id in ports:
                    _replace_dimensions(port, old, new)


# ---------------------------------------------------------------- kinds

def _apply_anchor(ctx: _Apply, data: dict) -> tuple:
    anchor = data.get("anchor_id")
    if data["target"] == "output_size":
        if anchor is None:
            if len(ctx.targets["output_targets"]) != 1:
                raise ValueError("output size is ambiguous; choose an output anchor")
            anchor = ctx.targets["output_targets"][0]
        if anchor not in ctx.targets["output_targets"]:
            raise ValueError("output_size must select an active output anchor")
    key = ("size", anchor)
    if key in ctx.seen:
        raise ValueError("duplicate size target")
    _anchor_size(ctx.candidate, anchor, (data["width"], data["height"]), ctx.targets)
    data["anchor_id"] = anchor
    return key


def _apply_node_size(ctx: _Apply, data: dict) -> tuple:
    node_id = data["node_id"]
    row = next((r for r in ctx.targets["nodes"] if r["id"] == node_id), None)
    if row is None or not row["size_supported"]:
        raise ValueError(f"unsupported node_size node: {node_id}")
    sim = ctx.variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})
    old, new = tuple(row["size"]), (data["width"], data["height"])
    anchor_id = row["size_anchor_id"]
    if ("size", anchor_id) in ctx.seen:
        raise ValueError("node size and anchor size overlap on the same surface")
    _anchor_size(ctx.candidate, anchor_id, new, ctx.targets)
    ctx.seen.add(("size", anchor_id))
    sim["width"], sim["height"] = new
    sim["inherit_shape"] = True
    sim["output_size"] = f"{new[0]}x{new[1]}"
    for direction in ("inputs", "outputs"):
        for port in sim.get(direction) or []:
            _replace_dimensions(port, old, new)
    return ("node_size", node_id)


def _apply_stream(ctx: _Apply, data: dict) -> tuple:
    stream = next((r for r in ctx.targets["streams"] if r["id"] == data["stream_id"]), None)
    if stream is None:
        raise ValueError(f"unknown stream size: {data['stream_id']}")
    old, new = tuple(stream["size"]), (data["width"], data["height"])
    for cfg in ctx.variant.node_configs.values():
        if isinstance(cfg, dict):
            _replace_sizes(cfg, old, new)
    if stream["primary"]:
        design = ctx.variant.design_conditions
        design["size"] = f"{new[0]}x{new[1]}"   # design_size_for_graph reads size before resolution
        for key in ("source_resolution", "resolution_size", "output_size"):
            if isinstance(design.get(key), str) and _size_tuple(design[key]) == old:
                design[key] = f"{new[0]}x{new[1]}"
    for buffer_id, b in _buffers(ctx.candidate).items():
        if _size_tuple(b.get("size")) == old:
            ctx.variant.buffer_overrides.setdefault(buffer_id, {})["size"] = f"{new[0]}x{new[1]}"
    return ("stream", stream["id"])


def _apply_fps(ctx: _Apply, data: dict) -> tuple:
    old = ctx.targets.get("fps")
    ctx.config.fps = data["value"]
    ctx.variant.design_conditions["fps"] = data["value"]
    # Explicit node rates would otherwise override the selected scenario-wide FPS.
    for node_id, cfg in ctx.variant.node_configs.items():
        if not isinstance(cfg, dict):
            continue
        sim = cfg.get("sim")
        if isinstance(sim, dict) and "fps" in sim:
            sim["fps"] = data["value"]
        if old and cfg.get("fps") == old:      # flat driver configs (decoder/encoder) at the stream rate
            cfg["fps"] = data["value"]
    return ("fps", None)


def _apply_clock(ctx: _Apply, data: dict) -> tuple:
    node_id = data["node_id"]
    row = next((r for r in ctx.targets["nodes"] if r["id"] == node_id), None)
    if row is None or not row["clock_supported"]:
        raise ValueError(f"unsupported node_clock_mhz node: {node_id}")
    cfg = ctx.variant.node_configs.setdefault(node_id, {})
    if cfg is None:
        cfg = ctx.variant.node_configs[node_id] = {}
    cfg.setdefault("sim", {})["manual_clock_mhz"] = data["value"]
    return ("node_clock_mhz", node_id)


def _apply_param(ctx: _Apply, data: dict) -> tuple:
    """Without node_id the parameter moves on every node that carries it (e.g. DPU + panel refresh)."""
    rows = [r for r in ctx.targets["params"] if r["param"] == data["param"] and r["modeled"]
            and (data.get("node_id") is None or r["node_id"] == data["node_id"])]
    if not rows:
        raise ValueError(f"unsupported node parameter: {data.get('node_id') or '*'}.{data['param']}")
    for row in rows:
        cfg = ctx.variant.node_configs[row["node_id"]]
        for block in (cfg, cfg.get("sim") if isinstance(cfg.get("sim"), dict) else None):
            if isinstance(block, dict) and data["param"] in block:
                block[data["param"]] = data["value"]
    return ("node_param", data.get("node_id"), data["param"])


def _apply_dvfs(ctx: _Apply, data: dict) -> tuple:
    """Pin a DVFS domain to an OPP level (every IP of the shared domain runs at that level)."""
    domain, level = data["domain"], data["level"]
    domains = {d["id"]: d for d in ctx.targets.get("domains") or []}
    row = domains.get(domain)
    if row is None:
        raise ValueError(f"unsupported DVFS domain: {domain} (this variant: {', '.join(domains) or 'none'})")
    if level not in {lv["level"] for lv in row["ladder"]}:
        raise ValueError(f"{domain} has no OPP level L{level}")
    ctx.config.dvfs_overrides = {**ctx.config.dvfs_overrides, domain: level}
    return ("dvfs_level", domain)


register(ChangeKind("output_size", "출력 크기 (MCSC out)", "size", "anchor_id", selector_optional=True, group="size",
                    description="녹화·미리보기 등 출력 surface 크기 (센서 입력은 유지)",
                    discover=lambda t: [{"id": a, "size": next(r["size"] for r in t["anchors"] if r["id"] == a),
                                         "role": next(r.get("role") for r in t["anchors"] if r["id"] == a)} for a in t["output_targets"]],
                    apply=_apply_anchor))
register(ChangeKind("anchor_size", "크기 기준점", "size", "anchor_id", group="size",
                    description="size_profile anchor (중간 buffer 포함)",
                    discover=lambda t: [{"id": r["id"], "size": r["size"]} for r in t["anchors"] if r["supported"]],
                    apply=_apply_anchor))
register(ChangeKind("node_size", "IP 처리 크기", "size", "node_id", group="size",
                    description="단일 surface에 묶인 IP의 처리 크기",
                    discover=lambda t: [{"id": n["id"], "size": n["size"]} for n in t["nodes"] if n["size_supported"]],
                    apply=_apply_node_size))
register(ChangeKind("stream_size", "스트림 크기", "size", "stream_id", group="size",
                    description="size anchor가 없는 scenario: 같은 크기로 정의된 surface(decoder·layer 등)를 함께 변경",
                    discover=lambda t: [{"id": s["id"], "size": s["size"], "primary": s["primary"], "where": s["where"]} for s in t["streams"]],
                    apply=_apply_stream))
register(ChangeKind("fps", "FPS", "value", None, unit="fps", max_value=240.0, group="clock",
                    description="scenario 처리 주기 (센서 mode 지원은 검증하지 않음)",
                    discover=lambda t: [{"id": "fps", "value": t["fps"]}] if t.get("fps") else [],
                    apply=_apply_fps))
register(ChangeKind("node_clock_mhz", "IP clock 하한", "value", "node_id", unit="MHz", max_value=5000.0, group="clock",
                    description="수동 하한 — DVFS·공유 domain 제약으로 더 높게 적용될 수 있음",
                    discover=lambda t: [{"id": n["id"], "ip": n["ip"]} for n in t["nodes"] if n["clock_supported"]],
                    apply=_apply_clock))
register(ChangeKind("node_param", "IP 설정값", "value", "node_id", needs_param=True, selector_optional=True,
                    description="IP 설정값 (예: display 주사율). IP를 비우면 그 설정을 가진 모든 IP에 함께 적용",
                    discover=lambda t: [{"id": r["node_id"], "param": r["param"], "label": r["label"], "unit": r["unit"], "value": r["value"]}
                                        for r in t["params"] if r["modeled"]],
                    apply=_apply_param))


register(ChangeKind("dvfs_level", "DVFS level", "level", "domain", unit="L", group="clock",
                    description="domain OPP level 고정 — 같은 domain의 모든 IP가 그 level로 동작 (요구 clock보다 낮으면 timing 미달)",
                    discover=lambda t: [{"id": d["id"], "level": d.get("level"), "mhz": d.get("mhz"), "ips": d.get("ips") or [],
                                         "ladder": d.get("ladder") or []} for d in t.get("domains") or []],
                    apply=_apply_dvfs))


def param_max(param: str | None) -> float | None:
    return NODE_PARAMS.get(param or "", (None, None, None, None))[2]


def apply_whatif_changes(graph, changes, config, domains: list[dict] | None = None, notes: list | None = None):
    """Return a detached graph/config. The loaded graph and all ORM JSON remain untouched.

    Structural levers run first (sensor -> power option -> chain size), the rest in request order, so a later
    size / compression condition applies to the reshaped pipeline. ``notes`` collects what a lever rewrote."""
    candidate = replace(graph, scenario=deepcopy(graph.scenario), variant=deepcopy(graph.variant))
    variant = candidate.variant
    variant.node_configs = deepcopy(variant.node_configs or {})
    variant.size_overrides = deepcopy(variant.size_overrides or {})
    variant.buffer_overrides = deepcopy(variant.buffer_overrides or {})
    variant.design_conditions = deepcopy(variant.design_conditions or {})
    ctx = _Apply(candidate, variant, config.model_copy(deep=True), whatif_targets(graph, config, domains))
    stream_changes = [c.model_dump(exclude_none=True) if hasattr(c, "model_dump") else dict(c)
                      for c in changes if (c.target if hasattr(c, "target") else c["target"]) == "stream_size"]
    stream_sizes = {r["id"]: tuple(r["size"]) for r in ctx.targets["streams"]}
    for change in stream_changes:
        if any(other["stream_id"] != change["stream_id"]
               and stream_sizes.get(other["stream_id"]) == (change["width"], change["height"])
               for other in stream_changes):
            raise ValueError("stream size changes overlap; compare these conditions separately")
    rows = []
    for index, change in enumerate(changes):
        data = change.model_dump(exclude_none=True) if hasattr(change, "model_dump") else dict(change)
        kind = CHANGE_KINDS.get(data["target"])
        if kind is None or kind.apply is None:
            raise ValueError(f"unsupported What-if target: {data['target']}")
        rows.append((kind.order, index, kind, data))
    normalized: list[dict | None] = [None] * len(rows)
    for _order, index, kind, data in sorted(rows, key=lambda r: (r[0], r[1])):
        key = kind.apply(ctx, data)
        if key in ctx.seen:
            raise ValueError("duplicate What-if change target")
        ctx.seen.add(key)
        normalized[index] = data
    _levers.validate_sensor_fps(ctx)
    if notes is not None:
        notes.extend(ctx.notes)
    return candidate, ctx.config, normalized


from scenario_db.api.services import whatif_levers as _levers  # noqa: E402,F401  (registers the lever kinds)
