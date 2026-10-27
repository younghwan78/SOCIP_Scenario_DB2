"""Commercialization levers for What-if — the changes a project team actually tries on a variant.

Registered into the same ``CHANGE_KINDS`` registry as the size / FPS / DVFS conditions, so the API schema,
the target listing, the LLM catalog and the UI editor pick them up without per-kind code elsewhere:

- ``sensor_mode``      : swap the sensor (another catalog sensor / DT mode). Readout timing follows the mode;
                         when the active size differs the camera chain is reshaped (RT chain, pyramid, anchors).
- ``chain_size``       : crop / downscale at one IP (bayer crop at BYRP, YUV downscale at YUVSC …) — every
                         downstream IP that processed the same size runs at the new size.
- ``power_knob``       : scenario-declared power options (``power_options.knobs`` with ``explore``), e.g.
                         ``crop_strategy=byrp_bcrop`` or ``pyramid_l0=skip`` (MTNR L0 bypass).
- ``history_interval`` : previous-frame (history) DMA once every N frames (30 fps -> 15 fps reference update).
- ``ip_mode``          : IP operating mode declared in the IP catalog (``capabilities.sim.modes``).
- ``compression``      : SBWC/AFBC mode per buffer (off / lossless / lossy / any SoC catalog mode, e.g. a
                         footprint-reduction mode) with the IP support check.

Each lever only rewrites a detached copy of the variant (see ``apply_whatif_changes``). Nothing is keyed by
SoC: availability comes from the variant's own data.
"""
from __future__ import annotations

import math
from typing import Any

from scenario_db.sim import power_options as po
from scenario_db.sim.bw_calc import compression_enabled, normalize_compression
from scenario_db.sim.graph_edges import edge_source, edge_target, edge_type
from scenario_db.sim.shape_propagation import _size_tuple

from scenario_db.api.services.whatif_conditions import ChangeKind, _Apply, _buffers, register
from scenario_db.api.services.whatif_geometry import (
    evidence, geometry_for_node, geometry_path, ip_sim, mode_compatibility, validate_geometry,
)

OTHER_PLACES = ("front", "tele", "ultrawide", "uw", "wide2", "macro")
_BAYER_TOKENS = ("BAYER", "RAW", "BGGR", "RGGB", "GRBG", "GBRG", "PDAF")
DEFAULT_RATIO = {"LOSSY": 0.5}


def reset_pipeline(graph) -> None:
    """The effective pipeline is cached per graph instance; drop it after a topology / ip_ref edit."""
    graph._pipeline_cache = None
    graph._node_by_id_cache = None


# ---------------------------------------------------------------- shared reshape helpers

def _sim(cfg: Any) -> dict:
    sim = (cfg or {}).get("sim") if isinstance(cfg, dict) else None
    return sim if isinstance(sim, dict) else {}


def _sim_size(graph, node_id: str) -> tuple[int, int] | None:
    sim = _sim((graph.variant.node_configs or {}).get(node_id))
    w, h = sim.get("width"), sim.get("height")
    return (w, h) if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0 else None


def scaled_size(anchor: tuple[int, int], old: tuple[int, int], new: tuple[int, int]) -> tuple[int, int] | None:
    """``anchor`` == ``old`` / 2^k (floor or ceil per axis, k = 0..6) -> ``new`` / 2^k with the same rounding."""
    if tuple(anchor) == tuple(old):
        return tuple(new)  # type: ignore[return-value]
    for k in range(1, 7):
        d = 2 ** k
        out = []
        for a, o, n in zip(anchor, old, new):
            if a == o // d:
                out.append(max(1, n // d))
            elif a == -(-o // d):
                out.append(max(1, -(-n // d)))
            else:
                break
        else:
            return out[0], out[1]
    return None


def _downstream(graph, start: str, size: tuple[int, int] | None) -> list[str]:
    """Nodes reached from ``start`` over data edges; with ``size`` only through nodes processing that size."""
    nxt: dict[str, set[str]] = {}
    for e in graph.pipeline_edges:
        if edge_type(e) == "CONTROL":
            continue
        nxt.setdefault(str(edge_source(e)), set()).add(str(edge_target(e)))
    active = {str(n.get("id")) for n in graph.pipeline_nodes}
    seen: list[str] = []
    stack = sorted(nxt.get(start, ()))
    while stack:
        node = stack.pop(0)
        if node in seen or node == start or node not in active:
            continue
        if size is not None and _sim_size(graph, node) != size:
            continue
        seen.append(node)
        stack.extend(sorted(nxt.get(node, ())))
    return seen


def _all_anchors(graph) -> dict[str, tuple[int, int]]:
    anchors = dict((graph.scenario.size_profile or {}).get("anchors") or {})
    anchors.update(graph.variant.size_overrides or {})
    return {k: _size_tuple(v) for k, v in anchors.items() if _size_tuple(v) != (0, 0)}


def _anchors_on(graph, nodes: set[str]) -> set[str]:
    """size_profile anchors of buffers produced / consumed / kept as history by ``nodes``."""
    buffers = _buffers(graph)
    out: set[str] = set()
    for e in graph.pipeline_edges:
        b = buffers.get(e.get("buffer"))
        if b and b.get("size_ref") and ({str(edge_source(e)), str(edge_target(e))} & nodes):
            out.add(str(b["size_ref"]))
    for b in buffers.values():
        for key in ("history", "dma"):
            if str((b.get(key) or {}).get("node_id") or "") in nodes and b.get("size_ref"):
                out.add(str(b["size_ref"]))
    return out


def _reshape(graph, nodes: list[str], anchors: set[str], old: tuple[int, int], new: tuple[int, int],
             *, preserve_outputs: bool = False, protected_anchors: set[str] | None = None) -> dict[str, Any]:
    """Rewrite ``old`` -> ``new`` (and its 2^-k pyramid levels) on the given nodes and anchors."""
    from scenario_db.api.services.whatif_conditions import _replace_sizes
    variant = graph.variant
    touched_nodes, touched_anchors = [], []
    for node_id in nodes:
        cfg = variant.node_configs.setdefault(node_id, {})
        sim = cfg.get("sim") or {}
        fixed = {k: sim[k] for k in ("output_width", "output_height", "width_out", "height_out", "output_size",
                                     "scale_size", "target_size", "scale", "crop") if k in sim} if preserve_outputs else {}
        from copy import deepcopy
        fixed = deepcopy(fixed)
        if _replace_sizes(cfg, old, new):
            touched_nodes.append(node_id)
        if fixed:
            cfg["sim"].update(fixed)
    current = _all_anchors(graph)
    for key in sorted(anchors):
        size = current.get(key)
        if size is None:
            continue
        to = scaled_size(size, old, new)
        if to is not None and to != size:
            variant.size_overrides[key] = f"{to[0]}x{to[1]}"
            touched_anchors.append(key)
    node_set = set(nodes)
    local_buffers = {e.get("buffer") for e in graph.pipeline_edges
                     if {str(edge_source(e)), str(edge_target(e))} & node_set}
    for buffer_id, b in _buffers(graph).items():
        if b.get("size_ref") in (protected_anchors or set()):
            continue
        explicit = _size_tuple(b.get("size"))
        owned = any(str((b.get(key) or {}).get("node_id") or "") in node_set for key in ("history", "dma"))
        if explicit == (0, 0) or not (buffer_id in local_buffers or owned or b.get("size_ref") in touched_anchors):
            continue
        to = scaled_size(explicit, old, new)
        if to is not None:
            variant.buffer_overrides.setdefault(buffer_id, {})["size"] = f"{to[0]}x{to[1]}"
    return {"nodes": touched_nodes, "anchors": touched_anchors}


# ---------------------------------------------------------------- sensor

def _props(row) -> dict:
    caps = getattr(row, "capabilities", None) or {}
    props = caps.get("properties") if isinstance(caps, dict) else None
    return props if isinstance(props, dict) else {}


def _place_anchor(key: str, place: str | None) -> bool:
    low = key.lower()
    if place and place != "rear":
        return low.startswith(f"{place}_")
    return not any(low.startswith(f"{p}_") for p in OTHER_PLACES)


def _readout_ms(mode: dict, height: int) -> float | None:
    pclk, llp = mode.get("sensor_pclk"), mode.get("sensor_line_length_pck")
    if isinstance(pclk, (int, float)) and isinstance(llp, (int, float)) and pclk > 0 and llp > 0 and height > 0:
        return round(height * llp / pclk * 1000.0, 2)
    v = mode.get("v_valid_ms")
    return float(v) if isinstance(v, (int, float)) else None


def sensor_targets(graph, fps: float | None) -> list[dict[str, Any]]:
    from scenario_db.sim.external_devices import _active_sensor_size, active_sensor_nodes, selected_sensor_mode
    rows = []
    sensors = {k: v for k, v in graph.ip_catalog.items() if str(getattr(v, "category", "") or "").lower() == "sensor"}
    for node in active_sensor_nodes(graph):
        node_id = str(node.get("id"))
        if node_id not in {str(n.get("id")) for n in graph.pipeline_nodes}:
            continue
        cur = selected_sensor_mode(graph, node) or {}
        cur_size = _size_tuple(cur.get("active_size") or cur.get("sensor_size"))
        if cur_size == (0, 0):
            continue
        cur_ip, cur_mode = str(node.get("ip_ref") or ""), str(cur.get("mode_id") or "")
        place = str(cur.get("place") or _props(graph.ip_catalog.get(cur_ip)).get("place") or "") or None
        choices: list[dict[str, Any]] = []
        for ip_id, row in sorted(sensors.items()):
            props = _props(row)
            raw_modes = props.get("modes")
            modes: dict = raw_modes if isinstance(raw_modes, dict) else {}
            for mode_id, mode in modes.items():
                if not isinstance(mode, dict) or str(mode.get("sensor_format") or "BAYER").upper() != "BAYER":
                    continue
                mfps = mode.get("sensor_fps")
                active, _src = _active_sensor_size(mode, graph)
                if not active:
                    continue
                is_cur = ip_id == cur_ip and str(mode_id) == cur_mode
                name = str(mode.get("sensor_name") or props.get("sensor_name") or ip_id)
                compatible = not (fps and isinstance(mfps, (int, float)) and mfps + 1e-6 < fps)
                choices.append({"id": f"{ip_id}#{mode_id}", "ip_ref": ip_id, "mode": str(mode_id), "sensor": name,
                                "place": props.get("place"), "size": list(active), "fps": mfps,
                                "bitwidth": mode.get("sensor_bitwidth"), "readout_ms": _readout_ms(mode, active[1]),
                                "current": is_cur, "fps_compatible": compatible,
                                "reason": None if compatible else f"목표 FPS를 {mfps:g} 이하로 함께 변경해야 함",
                                "evidence": {"status": "unverified", "source": "legacy_ip_catalog",
                                             "note": "크기/FPS가 같은 모드도 서로 다른 readout/기능을 가질 수 있음"},
                                "label": f"{name} · {active[0]}×{active[1]} · {mfps:g}fps · RAW{mode.get('sensor_bitwidth') or '?'}"
                                         if isinstance(mfps, (int, float)) else f"{name} · {active[0]}×{active[1]}"})
        area = cur_size[0] * cur_size[1]
        choices.sort(key=lambda c: (not c["current"], c["ip_ref"] != cur_ip, c["place"] != place,
                                    abs(c["size"][0] * c["size"][1] - area), c["fps"] or 0))
        rows.append({"id": node_id, "node_id": node_id, "ip_ref": cur_ip, "mode": cur_mode, "place": place,
                     "size": list(cur_size), "fps": cur.get("sensor_fps"), "bitwidth": cur.get("sensor_bitwidth"),
                     "readout_ms": _readout_ms(cur, cur_size[1]), "sensor": cur.get("sensor_name"),
                     "option_count": len(choices), "truncated": False,
                     "sensor_groups": [{"id": ip_id, "sensor": next(c["sensor"] for c in choices if c["ip_ref"] == ip_id),
                                        "count": sum(c["ip_ref"] == ip_id for c in choices)}
                                       for ip_id in dict.fromkeys(c["ip_ref"] for c in choices)],
                     "options": choices})
    return rows


def _apply_sensor(ctx: _Apply, data: dict) -> tuple:
    node_id, option = data["node_id"], data["option"]
    row = next((r for r in ctx.targets.get("sensors") or [] if r["node_id"] == node_id), None)
    if row is None:
        raise ValueError(f"no active sensor node: {node_id}")
    choice = next((c for c in row["options"] if c["id"] == option), None)
    if choice is None:
        raise ValueError(f"{node_id}: unknown sensor mode {option} (choose one listed for this variant)")
    graph = ctx.candidate
    if node_id in ctx.config.sensor_modes:
        raise ValueError(f"{node_id}: legacy sensor mode cannot override a pinned sensor binding")
    if choice["ip_ref"] != row["ip_ref"]:
        node = next((n for n in (graph.scenario.pipeline or {}).get("nodes") or [] if str(n.get("id")) == node_id), None)
        if node is None:
            raise ValueError(f"{node_id}: sensor node is not part of the scenario pipeline")
        node["ip_ref"] = choice["ip_ref"]
        reset_pipeline(graph)
    cfg = ctx.variant.node_configs.setdefault(node_id, {})
    for key in ("mode", "sensor_mode", "sensor_mode_ref", "resolved_sensor_mode", "sensor_readout"):
        cfg.pop(key, None)
    cfg["selected_mode"] = choice["mode"]
    design = ctx.variant.design_conditions
    if choice.get("bitwidth") and "sensor_bitwidth" in design:
        design["sensor_bitwidth"] = choice["bitwidth"]
    old, new = tuple(row["size"]), tuple(choice["size"])
    if old != new:
        nodes = _downstream(graph, node_id, None)
        anchors = _anchors_on(graph, set(nodes))
        anchors |= {k for k, v in _all_anchors(graph).items() if v == old and _place_anchor(k, row.get("place"))}
        moved = _reshape(graph, nodes, anchors, old, new)
        ctx.notes.append(f"센서 크기 {old[0]}x{old[1]} → {new[0]}x{new[1]}: IP {', '.join(moved['nodes']) or '없음'}"
                         + (f" · anchor {', '.join(moved['anchors'])}" if moved["anchors"] else ""))
        if new[0] * new[1] < max((a[0] * a[1] for k, a in _all_anchors(graph).items() if k.endswith("_out") and "record" in k), default=0):
            ctx.notes.append("센서 active 크기가 녹화 출력보다 작음 — upscale 경로 (화질 확인 필요)")
    ctx.notes.append(f"센서 {choice['label']} — readout {choice.get('readout_ms') or '?'} ms (기준 {row.get('readout_ms') or '?'} ms)")
    return ("sensor_mode", node_id)


def _apply_sensor_binding(ctx: _Apply, data: dict) -> tuple:
    from scenario_db.models.sensor import SensorModeBinding
    binding = SensorModeBinding.model_validate(data.get("sensor_binding"))
    node_id = data["node_id"]
    if data["option"] != f"{binding.catalog_ref}#{binding.mode_label}":
        raise ValueError("sensor binding option does not match its pinned catalog/mode")
    if ("sensor_mode", node_id) in ctx.seen:
        raise ValueError("legacy and pinned sensor changes overlap")
    if ctx.prepare_sensor is None:
        raise ValueError("pinned sensor binding requires authoritative catalog preparation")
    ctx.config.sensor_modes = {**ctx.config.sensor_modes, node_id: binding}
    ctx.candidate = ctx.prepare_sensor(ctx.candidate, ctx.config)
    ctx.variant = ctx.candidate.variant
    resolved = ctx.variant.node_configs[node_id].get("resolved_sensor_mode") or {}
    timing_note = "readout 근거 연결" if resolved.get("v_valid_ms") is not None else "readout timing 근거 없음"
    ctx.notes.append(f"센서 DT binding {binding.catalog_ref} · {binding.mode_label}: source hash · 설치 · transport 검증 · {timing_note}")
    return ("sensor_binding", node_id)


def validate_sensor_fps(ctx: _Apply) -> None:
    """Validate explicitly selected modes against the final cadence after all conditions."""
    fps = ctx.config.fps or ctx.variant.design_conditions.get("fps")
    if not fps:
        return
    for row in ctx.targets.get("sensors") or []:
        if ("sensor_mode", row["node_id"]) not in ctx.seen:
            continue
        mode = ctx.variant.node_configs[row["node_id"]]["selected_mode"]
        node = next(n for n in ctx.candidate.pipeline_nodes if str(n.get("id")) == row["node_id"])
        choice = next(c for c in row["options"] if c["mode"] == mode and c["ip_ref"] == node.get("ip_ref"))
        maximum = choice.get("fps")
        if isinstance(maximum, (int, float)) and maximum + 1e-6 < fps:
            raise ValueError(f"{row['node_id']}: selected sensor mode supports {maximum:g} fps, below requested {fps:g} fps")


# ---------------------------------------------------------------- crop / downscale at one IP

CHAIN_HINT = (("byrp", "bayer crop"), ("yuvsc", "YUV downscale"), ("rgbp", "RGB crop"), ("mcsc", "MCSC 입력 crop"))


def chain_targets(graph) -> list[dict[str, Any]]:
    """Only IPs with an explicit geometry capability and a connected output are offered."""
    rows = []
    for node in graph.pipeline_nodes:
        node_id = str(node.get("id"))
        size = _sim_size(graph, node_id)
        if size is None:
            continue
        geometry = geometry_for_node(graph, node_id)
        if geometry is None:
            continue
        ports = geometry["capabilities"][geometry["default_operation"]].get("ports") or []
        port = ports[0] if len(ports) == 1 else None
        down, affected_buffers = geometry_path(graph, node_id, size, port)
        if not down:
            continue
        hint = next((h for k, h in CHAIN_HINT if node_id.lower().startswith(k)), "crop / downscale")
        rows.append({"id": node_id, "size": list(size), "downstream": down, "hint": hint,
                     "geometry": geometry, "evidence": geometry["evidence"], "affected_buffers": affected_buffers,
                     "label": f"{node_id} 이후 {len(down)}개 IP ({hint})"})
    # the usual crop / downscale points (bayer crop, YUV downscale) first, then the longest chains
    rank = {k: i for i, (k, _h) in enumerate(CHAIN_HINT)}
    rows.sort(key=lambda r: (min((v for k, v in rank.items() if str(r["id"]).lower().startswith(k)), default=len(rank)),
                             -len(r["downstream"])))
    return rows


def _apply_chain(ctx: _Apply, data: dict) -> tuple:
    node_id = data["node_id"]
    graph = ctx.candidate
    old = _sim_size(graph, node_id)
    if old is None:
        raise ValueError(f"{node_id}: no processing size to crop/scale from")
    new = (data["width"], data["height"])
    operation, port, geometry = validate_geometry(graph, node_id, data, old)
    down, _ = geometry_path(graph, node_id, old, port)
    if not down:
        raise ValueError(f"{node_id}: no downstream IP processes {old[0]}x{old[1]}")
    anchors = _anchors_on(graph, set(down))
    # A fixed record/preview output is an explicit product requirement, even
    # when it happens to have the same numeric size as the original input.
    from scenario_db.api.services.whatif_conditions import _anchor_role
    nodes_by_id = {str(n.get("id")): n for n in graph.pipeline_nodes}
    protected = {a for a in _all_anchors(graph) if _anchor_role(graph, a, _buffers(graph), nodes_by_id) is not None}
    anchors -= protected
    moved = _reshape(graph, down, anchors, old, new, preserve_outputs=True, protected_anchors=protected)
    sim = ctx.variant.node_configs.setdefault(node_id, {}).setdefault("sim", {})
    transform = {"width": new[0], "height": new[1]}
    if operation == "crop":
        transform.update(x=data.get("x") or 0, y=data.get("y") or 0)
    sim[operation] = transform
    sim["output_width"], sim["output_height"] = new
    if not geometry["limits_complete"]:
        ctx.notes.append(f"{node_id}: 선언된 모델 범위 검증 · 전체 하드웨어 크기/ratio 한계는 미검증")
    ctx.notes.append(f"{node_id} {old[0]}x{old[1]} → {new[0]}x{new[1]}: 이후 IP {', '.join(moved['nodes']) or '없음'}"
                     + (f" · anchor {', '.join(moved['anchors'])}" if moved["anchors"] else ""))
    return ("chain_size", node_id)


# ---------------------------------------------------------------- power options (knobs) / IP modes

def knob_targets(graph) -> list[dict[str, Any]]:
    try:
        dims, _notes = po.option_dimensions(graph, include_modes=False)
    except Exception:  # an authoring error in power_options must not hide the other levers
        return []
    return [{"id": d["name"], "param": d["name"], "label": d["label"], "current": d["current"],
             "options": [{"id": i["value"], "label": f"{d['label']} ({i['value']})", "iq_eval": i.get("iq_eval"), "note": i.get("note")}
                         for i in d["items"]]} for d in dims]


def _apply_knob(ctx: _Apply, data: dict) -> tuple:
    name, value = data["param"], data["option"]
    dims, _ = po.option_dimensions(ctx.candidate, include_modes=False)
    dim = next((d for d in dims if d["name"] == name), None)
    item = next((i for i in (dim or {}).get("items") or [] if i["value"] == value), None)
    if item is None:
        raise ValueError(f"power option {name}={value} is not available for this variant")
    patched = po.apply_option_set(ctx.candidate, [item]).variant
    for f in po.VARIANT_FIELDS:
        value_ = getattr(patched, f, None)
        setattr(ctx.variant, f, value_ if value_ is not None else ({} if f != "tags" else []))
    reset_pipeline(ctx.candidate)
    return ("power_knob", name)


def mode_targets(graph) -> list[dict[str, Any]]:
    rows = []
    for r in po.ip_mode_table(graph):
        if not r["alternatives"]:
            continue
        sim = ip_sim(graph, r["node"])
        options = []
        for a in r["alternatives"]:
            params = (sim.get("modes") or {}).get(a["mode"]) or {}
            supported, reason = mode_compatibility(graph, r["node"], params)
            options.append({"id": a["mode"], "label": a.get("label") or a["mode"], "explorable": a["explorable"],
                            "unit_power_mw_mp": a["unit_power_mw_mp"], "ppc": a["ppc"], "note": a.get("note"),
                            "supported": supported, "reason": reason, "requires": params.get("requires"),
                            "iq_eval": params.get("iq_eval", "required"),
                            "evidence": evidence(sim, params), "effects": ["IP unit power", "PPC / required clock"]})
        rows.append({"id": r["node"], "mode": r["mode"], "hw_name": r["hw_name"], "unit_power_mw_mp": r["unit_power_mw_mp"],
                     "ppc": r["ppc"], "options": options})
    return rows


def _apply_mode(ctx: _Apply, data: dict) -> tuple:
    node_id, mode = data["node_id"], data["option"]
    row = next((r for r in ctx.targets.get("ip_modes") or [] if r["id"] == node_id), None)
    if row is None or mode not in {o["id"] for o in row["options"]}:
        raise ValueError(f"{node_id}: mode {mode} is not declared for this IP")
    cfg = ctx.variant.node_configs.setdefault(node_id, {})
    cfg.setdefault("sim", {})["mode"] = mode
    cfg["selected_mode"] = mode
    return ("ip_mode", node_id)


def validate_ip_modes(ctx: _Apply) -> None:
    """Check final geometry and cadence, independent of condition input order."""
    for key in ctx.seen:
        if key[0] != "ip_mode":
            continue
        node_id = key[1]
        mode = ctx.variant.node_configs[node_id]["selected_mode"]
        sim = ip_sim(ctx.candidate, node_id)
        params = (sim.get("modes") or {}).get(mode) or {}
        supported, reason = mode_compatibility(ctx.candidate, node_id, params, ctx.config.fps)
        if supported is False:
            raise ValueError(f"{node_id}: {reason}")
        if supported is None:
            ctx.notes.append(f"{node_id} {mode}: {reason}")
        basis = evidence(sim, params)
        ctx.notes.append(f"{node_id} {mode} 모델 근거: {basis['status']} · {basis['source']}")


# ---------------------------------------------------------------- history (previous-frame) DMA rate

def history_targets(graph) -> list[dict[str, Any]]:
    active = {str(n.get("id")) for n in graph.pipeline_nodes}
    rows = []
    for bid, b in sorted(_buffers(graph).items()):
        h = b.get("history") or {}
        node = str(h.get("node_id") or "")
        if node not in active or h.get("frame_offset") != -1:
            continue
        rows.append({"id": bid, "node": node, "ports": len(h.get("read_ports") or []) + len(h.get("write_ports") or []),
                     "value": float(h.get("update_interval") or 1), "format": b.get("format"),
                     "compression": normalize_compression(b.get("compression")) or "OFF"})
    return rows


def _apply_history(ctx: _Apply, data: dict) -> tuple:
    rows = ctx.targets.get("history") or []
    bid = data.get("buffer_id")
    picked = [r for r in rows if bid is None or r["id"] == bid]
    if not picked:
        raise ValueError(f"no previous-frame (history) DMA buffer: {bid or 'any'}")
    if float(data["value"]) != int(data["value"]) or not 1 <= data["value"] <= 8:
        raise ValueError("history update interval must be a whole number of frames (1-8)")
    if any(k[0] == "history_interval" and (k[1] is None or bid is None) for k in ctx.seen):
        raise ValueError("history interval for all buffers overlaps a per-buffer interval")
    for r in picked:
        hist = ctx.variant.buffer_overrides.setdefault(r["id"], {}).setdefault("history", {})
        hist["update_interval"] = int(data["value"])
    return ("history_interval", bid)


# ---------------------------------------------------------------- compression (SBWC / AFBC)

def _family(fmt: str) -> str:
    return "BAYER" if any(t in fmt.upper() for t in _BAYER_TOKENS) else "YUV"


def _catalog(graph) -> dict[str, dict]:
    modes = getattr(getattr(graph, "soc", None), "compression_modes", None) or {}
    out = {}
    for name, entry in modes.items():
        get = entry.get if isinstance(entry, dict) else (lambda k, e=entry: getattr(e, k, None))
        out[str(name)] = {"comp_ratio": get("comp_ratio"), "typical_ratio": get("typical_ratio"),
                          "compressor": get("compressor"), "note": get("note")}
    return out


def compression_targets(graph) -> list[dict[str, Any]]:
    from scenario_db.sim.arch_exploration import _buffer_nodes, _support, compression_support
    catalog = _catalog(graph)
    active = {str(n.get("id")) for n in graph.pipeline_nodes}
    buffers = _buffers(graph)
    rows = []
    for bid, nodes in sorted(_buffer_nodes(graph).items()):
        live = nodes & active
        b = buffers.get(bid)
        if not live or b is None or b.get("size_status") == "unknown" or not b.get("format"):
            continue
        fmt = str(b.get("format"))
        fam = _family(fmt)
        _sup, listed = _support(graph, live)
        if not listed:   # no endpoint IP declares compression: not a switchable SBWC/AFBC DMA
            continue
        names = sorted(m for m in catalog if m.startswith(f"COMP_{fam}_")) or [f"COMP_{fam}_LOSSLESS", f"COMP_{fam}_LOSSY"]
        current = normalize_compression(b.get("compression"))
        options = [{"id": "COMP_OFF", "label": "압축 끔", "ratio": 1.0, "ratio_source": "off", "lossy": False, "supported": True}]
        for m in names:
            c = catalog.get(m, {})
            typ, worst = c.get("typical_ratio"), c.get("comp_ratio")
            suffix = m[len(f"COMP_{fam}_"):]
            if typ is not None and typ < 1:
                ratio, src = float(typ), "typical"
            elif worst is not None and worst < 1:
                ratio, src = float(worst), "catalog"
            elif suffix.split("_")[0] in DEFAULT_RATIO and m not in catalog:
                ratio, src = DEFAULT_RATIO[suffix.split("_")[0]], "assumed"
            else:
                ratio, src = float(worst if worst is not None else 1.0), "catalog"
            supported, reason, _ = compression_support(graph, live, m)
            options.append({"id": m, "label": suffix.replace("_", " ").lower(), "ratio": ratio, "ratio_source": src,
                            "lossy": "LOSSY" in suffix, "supported": supported, "support_reason": reason,
                            "compressor": c.get("compressor"), "note": c.get("note")})
        rows.append({"id": bid, "format": fmt, "family": fam, "nodes": sorted(live), "current": current or "COMP_OFF",
                     "current_ratio": b.get("comp_ratio"), "llc": bool((b.get("placement") or {}).get("llc_allocated")),
                     "history": bool(b.get("history")), "declared": sorted(listed),
                     "undeclared": sorted(live - set(listed)), "options": options})
    # buffers already compressed first (mode change), then by id
    rows.sort(key=lambda r: (r["current"] == "COMP_OFF", r["id"]))
    return rows


def _apply_compression(ctx: _Apply, data: dict) -> tuple:
    bid, mode = data["buffer_id"], data["option"]
    row = next((r for r in ctx.targets.get("buffers") or [] if r["id"] == bid), None)
    if row is None:
        raise ValueError(f"unknown or inactive buffer: {bid}")
    opt = next((o for o in row["options"] if o["id"] == mode), None)
    if opt is None:
        raise ValueError(f"{bid}: compression {mode} is not in the SoC catalog for {row['family']}")
    if opt["supported"] is False:
        raise ValueError(f"{bid}: {', '.join(row['declared'])} IP catalog does not list {mode}")
    if opt["supported"] is None and mode != "COMP_OFF":
        ctx.notes.append(f"{bid} {mode}: {opt.get('support_reason') or 'compression support not declared'}"
                         " — 조합 탐색(지원 DMA만)에서는 제외되는 조건")
    override = ctx.variant.buffer_overrides.setdefault(bid, {})
    if mode == "COMP_OFF":
        override.update({"compression": "COMP_OFF", "comp_ratio": None})
    else:
        ratio = data.get("value")
        if ratio is not None and not 0 < ratio <= 1:
            raise ValueError("compression ratio must be in (0, 1]")
        override.update({"compression": mode, "comp_ratio": float(ratio if ratio is not None else opt["ratio"])})
    return ("compression", bid)


# ---------------------------------------------------------------- LLC allocation

def llc_targets(graph) -> list[dict[str, Any]]:
    """DMA buffers of active nodes with their LLC placement. The default weight for a new allocation is the
    buffer's own ``llc_weight``, else the median of the scenario's allocated buffers (else the request value)."""
    from statistics import median

    from scenario_db.sim.arch_exploration import _buffer_nodes
    from scenario_db.sim.transfers import _effective_buffer
    active = {str(n.get("id")) for n in graph.pipeline_nodes}
    rows, weights = [], []
    for bid, nodes in sorted(_buffer_nodes(graph).items()):
        b = _effective_buffer(graph, bid)
        if not nodes & active or not b or b.get("size_status") == "unknown" or not b.get("format"):
            continue
        place = b.get("placement") or {}
        on = bool(place.get("llc_allocated"))
        weight = float(place["llc_weight"]) if place.get("llc_weight") is not None else None
        if on and weight is not None:
            weights.append(weight)
        rows.append({"id": bid, "format": b.get("format"), "nodes": sorted(nodes & active), "current": "on" if on else "off",
                     "weight": weight, "allocation_mb": place.get("llc_allocation_mb"),
                     "compression": normalize_compression(b.get("compression")) or "COMP_OFF"})
    default = round(median(weights), 3) if weights else None
    for r in rows:
        w = r["weight"] if r["weight"] is not None else default
        r["options"] = [{"id": "off", "label": "LLC 끔 (DRAM)", "current": r["current"] == "off"},
                        {"id": "on", "label": "LLC 할당" + (f" · weight {w:g}" if w is not None else " · weight 입력 필요"),
                         "weight": w, "weight_source": "buffer" if r["weight"] is not None else "scenario median" if w is not None else None,
                         "current": r["current"] == "on"}]
    rows.sort(key=lambda r: (r["current"] != "on", r["id"]))
    return rows


def _apply_llc(ctx: _Apply, data: dict) -> tuple:
    bid, option = data["buffer_id"], data["option"]
    row = next((r for r in ctx.targets.get("llc") or [] if r["id"] == bid), None)
    if row is None:
        raise ValueError(f"unknown or inactive DMA buffer: {bid}")
    if option not in ("on", "off"):
        raise ValueError("LLC option must be on or off")
    override = ctx.variant.buffer_overrides.setdefault(bid, {})
    place = dict(override.get("placement") or {})
    if option == "off":
        place.update(llc_allocated=False)
    else:
        weight = data.get("value") if data.get("value") is not None else row["options"][1]["weight"]
        if weight is None or not 0 < float(weight) <= 1:
            raise ValueError(f"{bid}: LLC weight (DRAM byte fraction, 0-1] is required")
        place.update(llc_allocated=True, llc_weight=float(weight))
        ctx.notes.append(f"{bid} LLC weight {float(weight):g}: LLC 용량 · 다른 할당과의 경합은 모델하지 않음 (DRAM BW × weight)")
    override["placement"] = place
    return ("llc_alloc", bid)


# ---------------------------------------------------------------- registry

def lever_targets(graph, fps: float | None) -> dict[str, Any]:
    return {"sensors": sensor_targets(graph, fps), "chains": chain_targets(graph), "knobs": knob_targets(graph),
            "ip_modes": mode_targets(graph), "history": history_targets(graph), "buffers": compression_targets(graph),
            "llc": llc_targets(graph)}


register(ChangeKind("sensor_mode", "센서 변경", "choice", "node_id", group="sensor", order=10, iq="required",
                    description="다른 sensor / DT mode로 교체 — readout timing은 mode 값, 크기가 다르면 RT chain · pyramid가 함께 바뀜",
                    discover=lambda t: t.get("sensors") or [], apply=_apply_sensor))
register(ChangeKind("sensor_binding", "검토된 센서 DT 모드", "choice", "node_id", group="sensor", order=10, iq="required",
                    description="설치된 source board의 DT/CIS 모드와 입력 hash를 고정한 센서 실험 (target 배선 호환성은 별도 검증)",
                    discover=lambda t: t.get("sensor_bindings") or [], apply=_apply_sensor_binding))
register(ChangeKind("chain_size", "IP crop · downscale", "size", "node_id", group="size", order=30, iq="required",
                    description="선택 IP에서 crop/downscale — 이후 같은 크기를 처리하던 IP가 모두 새 크기로 동작 (bayer crop · YUV downscale)",
                    discover=lambda t: t.get("chains") or [], apply=_apply_chain))
register(ChangeKind("power_knob", "Power option", "choice", "param", needs_param=True, group="temporal", order=20, iq="required",
                    description="scenario에 선언된 power option (bayer crop 전략, MTNR L0 skip 등) — IQ 평가 필요",
                    discover=lambda t: t.get("knobs") or [], apply=_apply_knob))
register(ChangeKind("history_interval", "Previous DMA 빈도", "value", "buffer_id", selector_optional=True, unit="frame",
                    max_value=8.0, group="temporal", iq="required",
                    description="history(f-1) DMA read/write를 N frame에 한 번 — 30fps에서 N=2면 15fps 갱신 (buffer 미지정 = 전체)",
                    discover=lambda t: t.get("history") or [], apply=_apply_history))
register(ChangeKind("ip_mode", "IP mode", "choice", "node_id", group="mode", iq="required",
                    description="IP catalog에 선언된 동작 mode (unit power · PPC가 mode별로 다름)",
                    discover=lambda t: t.get("ip_modes") or [], apply=_apply_mode))
register(ChangeKind("compression", "SBWC 압축", "choice", "buffer_id", value_optional=True, group="compression",
                    description="buffer 압축 on/off · mode 변경 (lossless ↔ lossy · footprint 등 SoC catalog mode). ratio = typical(평균) → catalog",
                    discover=lambda t: t.get("buffers") or [], apply=_apply_compression))
register(ChangeKind("llc_alloc", "LLC 할당", "choice", "buffer_id", value_optional=True, group="compression",
                    description="buffer를 LLC에 할당 / 해제 — DRAM BW × llc_weight (value = weight, 기본 = buffer 값 → scenario 중앙값). 용량 경합 미모델",
                    discover=lambda t: t.get("llc") or [], apply=_apply_llc))
