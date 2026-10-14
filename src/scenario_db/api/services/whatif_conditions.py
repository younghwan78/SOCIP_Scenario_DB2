"""Reversible conditions over an effective graph, with explicit shape boundaries."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.shape_propagation import _size_tuple, propagate_shapes


def _buffers(graph):
    overrides = graph.variant.buffer_overrides or {}
    return {key: {**(value or {}), **(overrides.get(key) or {})}
            for key, value in ((graph.scenario.pipeline or {}).get("buffers") or {}).items()}


def whatif_targets(graph, config=None) -> dict[str, Any]:
    anchors = dict((graph.scenario.size_profile or {}).get("anchors") or {})
    anchors.update(graph.variant.size_overrides or {})
    buffers = _buffers(graph)
    used_buffers = {str(e.get("buffer")) for e in graph.pipeline_edges if e.get("buffer")}
    used_refs = {str(b.get("size_ref")) for key, b in buffers.items()
                 if key in used_buffers and b.get("size_ref")}
    inputs = build_simulation_inputs(graph, config)
    workloads = {w.node_id: w for w in inputs.workloads}
    shapes = propagate_shapes(graph)
    rows = []
    for key, value in sorted(anchors.items()):
        kind = "sensor" if "sensor" in key.lower() else "output" if any(
            token in key.lower() for token in ("record_out", "preview_out", "video_out", "output")) else "intermediate"
        width, height = _size_tuple(value)
        if not width or not height or (key not in used_refs and kind != "sensor"):
            continue
        rows.append({"id": key, "size": [width, height], "kind": kind,
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
                      "size": [workload.width, workload.height], "size_supported": size_supported,
                      "size_anchor_id": size_anchors[0] if size_supported else None,
                      "clock_supported": workload.sim_params.ppc > 0,
                      "input_size": [shape.input.width, shape.input.height] if shape else None})
    fps = (config.fps if config is not None and getattr(config, "fps", None) else None) \
        or (graph.variant.design_conditions or {}).get("fps")
    return {"anchors": rows, "nodes": nodes, "fps": float(fps) if fps else None,
            "output_targets": [r["id"] for r in rows if r["kind"] == "output" and r["supported"]],
            "supported_changes": ["anchor_size", "node_size", "output_size", "fps", "node_clock_mhz"],
            "limitations": ["Exynos2600 only", "Sensor mode changes require Sensor Explore catalog selection",
                            "SW per-frame runtime and bitstream bitrate stay fixed unless modeled by the existing engine",
                            "Node clock values are manual lower bounds; DVFS/domain constraints may select a higher clock",
                            "FPS changes are hypothetical cadence; sensor catalog FPS support is not validated",
                            "Measured replay/projection cannot be extrapolated", "IQ and hardware wiring are not validated"]}


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


def apply_whatif_changes(graph, changes, config):
    """Return a detached graph/config. The loaded graph and all ORM JSON remain untouched."""
    candidate = replace(graph, scenario=deepcopy(graph.scenario), variant=deepcopy(graph.variant))
    variant = candidate.variant
    variant.node_configs = deepcopy(variant.node_configs or {})
    variant.size_overrides = deepcopy(variant.size_overrides or {})
    variant.buffer_overrides = deepcopy(variant.buffer_overrides or {})
    variant.design_conditions = deepcopy(variant.design_conditions or {})
    candidate_config = config.model_copy(deep=True)
    targets = whatif_targets(graph, config)
    seen: set[tuple[str, str | None]] = set()
    normalized = []
    for change in changes:
        data = change.model_dump(exclude_none=True) if hasattr(change, "model_dump") else dict(change)
        target = data["target"]
        if target in {"anchor_size", "output_size"}:
            anchor = data.get("anchor_id")
            if target == "output_size" and anchor is None:
                if len(targets["output_targets"]) != 1:
                    raise ValueError("output size is ambiguous; choose an output anchor")
                anchor = targets["output_targets"][0]
            if target == "output_size" and anchor not in targets["output_targets"]:
                raise ValueError("output_size must select an active output anchor")
            key = ("size", anchor)
            if key in seen:
                raise ValueError("duplicate size target")
            _anchor_size(candidate, anchor, (data["width"], data["height"]), targets)
            data["anchor_id"] = anchor
        elif target in {"node_size", "node_clock_mhz"}:
            node_id = data["node_id"]
            row = next((r for r in targets["nodes"] if r["id"] == node_id), None)
            if row is None or not row["size_supported" if target == "node_size" else "clock_supported"]:
                raise ValueError(f"unsupported {target} node: {node_id}")
            key = (target, node_id)
            sim = variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})
            if target == "node_clock_mhz":
                sim["manual_clock_mhz"] = data["value"]
            else:
                old, new = tuple(row["size"]), (data["width"], data["height"])
                anchor_id = row["size_anchor_id"]
                if ("size", anchor_id) in seen:
                    raise ValueError("node size and anchor size overlap on the same surface")
                _anchor_size(candidate, anchor_id, new, targets)
                seen.add(("size", anchor_id))
                sim["width"], sim["height"] = new
                sim["inherit_shape"] = True
                sim["output_size"] = f"{new[0]}x{new[1]}"
                for direction in ("inputs", "outputs"):
                    for port in sim.get(direction) or []:
                        _replace_dimensions(port, old, new)
        elif target == "fps":
            key = ("fps", None)
            candidate_config.fps = data["value"]
            variant.design_conditions["fps"] = data["value"]
            # Existing explicit node rates would otherwise override the selected scenario-wide FPS.
            for row in targets["nodes"]:
                sim = variant.node_configs.setdefault(row["id"], {}).setdefault("sim", {})
                if "fps" in sim:
                    sim["fps"] = data["value"]
        else:
            raise ValueError(f"unsupported What-if target: {target}")
        if key in seen:
            raise ValueError("duplicate What-if change target")
        seen.add(key)
        normalized.append(data)
    return candidate, candidate_config, normalized
