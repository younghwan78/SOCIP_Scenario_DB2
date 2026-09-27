"""Power-saving options explored on top of a formal variant.

An option is one alternative that may lower power but needs IQ (image quality)
evaluation before a project can adopt it, so it is never registered as a
scenario variant. Two kinds:

- knob     : architecture knob value (scenario ``power_options.knobs`` with
             ``explore``), e.g. ``crop_strategy=byrp_bcrop``, ``pyramid_l0=skip``.
             Re-applied at run time with the authoring knob engine (sizes,
             bindings, topology patch) -> the graph is rebuilt and re-simulated.
- ip_mode  : IP operating mode whose ``capabilities.sim.modes.<mode>`` declares
             ``substitutes: [<current mode>]`` (e.g. a LowPower mode of MTNR with
             its own unit_power / ppc / idc) -> the node's sim mode is swapped.

Each explored dimension holds the current value plus its alternatives; the full
factorial of the dimensions (minus the all-current set) is evaluated, capped by
``max_sets``.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import replace
from itertools import product
from typing import Any

from scenario_db.authoring.knobs import KnobError, apply_knobs, selected_values
from scenario_db.authoring.knobs import _match as knob_condition_match
from scenario_db.sim.workloads import is_external_non_compute_node, mode_sim_params

VARIANT_FIELDS = (
    "design_conditions", "size_overrides", "routing_switch", "topology_patch",
    "node_configs", "buffer_overrides", "tags",
)


def knob_key(name: str, value: str) -> str:
    return f"knob:{name}={value}"


def mode_key(node: str, mode: str) -> str:
    return f"mode:{node}={mode}"


def variant_dict(variant: Any) -> dict[str, Any]:
    out = {"id": getattr(variant, "id", None)}
    for f in VARIANT_FIELDS:
        out[f] = deepcopy(getattr(variant, f, None) or ({} if f != "tags" else []))
    return out


def _sim_block(ip_row: Any) -> dict[str, Any]:
    caps = getattr(ip_row, "capabilities", None) or {}
    sim = caps.get("sim") or (caps.get("properties") or {}).get("sim") or {}
    return sim if isinstance(sim, dict) else {}


def current_mode(graph: Any, node_id: str) -> str:
    cfg = (graph.variant.node_configs or {}).get(node_id) or {}
    sim = cfg.get("sim") or {}
    return str((sim.get("mode") if isinstance(sim, dict) else None) or cfg.get("selected_mode") or "Normal")


def _substitutes(params: dict[str, Any]) -> list[str]:
    subs = params.get("substitutes") or []
    return [str(s) for s in (subs if isinstance(subs, list) else [subs])]


def option_dimensions(graph: Any, *, include_knobs: bool = True, include_modes: bool = True
                      ) -> tuple[list[dict[str, Any]], list[str]]:
    """Explorable dimensions of this variant + notes on declared options that do not apply."""
    dims: list[dict[str, Any]] = []
    notes: list[str] = []
    spec = getattr(graph.scenario, "power_options", None) or {}
    vdoc = variant_dict(graph.variant)
    if include_knobs and spec.get("knobs"):
        try:
            selected = selected_values(spec, vdoc)
        except KnobError as exc:
            notes.append(str(exc))
            selected = {}
        for name, knob in spec["knobs"].items():
            explore = knob.get("explore")
            if not explore or name not in selected:
                continue
            label = explore.get("label") or name
            if not knob_condition_match(vdoc, explore):
                notes.append(f"{label}: not applicable to this variant ({_cond_text(explore)})")
                continue
            current = selected[name]
            if current != knob.get("default"):
                notes.append(f"{label}: variant already selects '{current}' (adopted)")
                continue
            alts = [v for v in knob.get("values") or {} if v != current]
            if not alts:
                continue
            dims.append({
                "id": f"knob:{name}", "kind": "knob", "name": name, "label": label, "current": current,
                "items": [{
                    "key": knob_key(name, v), "kind": "knob", "dimension": f"knob:{name}", "knob": name,
                    "value": v, "from": current, "label": f"{label}: {v}",
                    "iq_eval": explore.get("iq_eval", "required"), "note": explore.get("note"),
                } for v in alts],
            })
    if include_modes:
        for node in graph.pipeline_nodes:
            node_id = str(node.get("id") or "")
            ip_ref = node.get("ip_ref")
            row = graph.ip_catalog.get(str(ip_ref)) if ip_ref else None
            if not node_id or row is None or is_external_non_compute_node(node, row):
                continue
            if ((graph.variant.node_configs or {}).get(node_id) or {}).get("sw_timing"):
                continue
            sim = _sim_block(row)
            modes = sim.get("modes") or {}
            if not isinstance(modes, dict):
                continue
            cur = current_mode(graph, node_id)
            cur_params = mode_sim_params(sim, cur)
            items = []
            for mode, params in modes.items():
                if not isinstance(params, dict) or str(mode).lower() == cur.lower():
                    continue
                if cur.lower() not in [s.lower() for s in _substitutes(params)]:
                    continue
                items.append({
                    "key": mode_key(node_id, str(mode)), "kind": "ip_mode", "dimension": f"mode:{node_id}",
                    "node": node_id, "ip_ref": str(ip_ref), "value": str(mode), "from": cur,
                    "label": params.get("label") or f"{node_id.upper()} {mode}",
                    "iq_eval": params.get("iq_eval", "required"), "note": params.get("note"),
                    "unit_power_mw_mp": params.get("unit_power_mw_mp"),
                    "from_unit_power_mw_mp": cur_params.get("unit_power_mw_mp", sim.get("unit_power_mw_mp")),
                    "ppc": params.get("ppc"), "from_ppc": cur_params.get("ppc", sim.get("ppc")),
                    "source": params.get("source") or sim.get("source"),
                })
            if items:
                dims.append({"id": f"mode:{node_id}", "kind": "ip_mode", "node": node_id, "ip_ref": str(ip_ref),
                             "label": f"{node_id} mode", "current": cur, "items": items})
    return dims, notes


def _cond_text(explore: dict[str, Any]) -> str:
    parts = []
    if explore.get("when_node_enabled"):
        parts.append(f"needs node '{explore['when_node_enabled']}' enabled")
    for k, v in (explore.get("when") or {}).items():
        parts.append(f"{k}={v}")
    return ", ".join(parts) or "condition"


def count_sets(dims: list[dict[str, Any]]) -> int:
    return math.prod(len(d["items"]) + 1 for d in dims) - 1 if dims else 0


def option_sets(dims: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Full factorial over the dimensions (current value = no item), all-current excluded."""
    choices = [[None, *d["items"]] for d in dims]
    out = []
    for combo in product(*choices):
        items = [c for c in combo if c is not None]
        if items:
            out.append(items)
    out.sort(key=lambda s: (len(s), [i["key"] for i in s]))
    return out


def set_key(items: list[dict[str, Any]]) -> str:
    return "+".join(sorted(i["key"] for i in items))


def apply_option_set(graph: Any, items: list[dict[str, Any]]) -> Any:
    """A graph copy whose variant carries the option values (knob patch / sim mode)."""
    variant = deepcopy(graph.variant)
    knob_items = [i for i in items if i["kind"] == "knob"]
    if knob_items:
        spec = getattr(graph.scenario, "power_options", None) or {}
        vdoc = variant_dict(variant)
        changed = {}
        for it in knob_items:
            knob = spec["knobs"][it["knob"]]
            vdoc["design_conditions"][knob.get("condition_key") or it["knob"]] = it["value"]
            changed[it["knob"]] = knob
        base_anchors = dict(((getattr(graph.scenario, "size_profile", None) or {}).get("anchors") or {}))
        # only the changed knobs: the variant already carries the effect of its current values
        apply_knobs(base_anchors, vdoc, {**{k: v for k, v in spec.items() if k != "knobs"}, "knobs": changed})
        for f in VARIANT_FIELDS:
            setattr(variant, f, vdoc.get(f))
    for it in items:
        if it["kind"] != "ip_mode":
            continue
        cfgs = dict(variant.node_configs or {})
        cfg = deepcopy(cfgs.get(it["node"]) or {})
        sim = dict(cfg.get("sim") or {})
        sim["mode"] = it["value"]
        cfg["sim"] = sim
        cfg["selected_mode"] = it["value"]
        cfgs[it["node"]] = cfg
        variant.node_configs = cfgs
    return replace(graph, variant=variant)
