"""Architecture knobs: named alternatives selected per variant.

``knobs.yaml`` (scenario authoring dir)::

    params:                      # scenario-wide defaults, overridable per variant
      sensor_margin_pct: 25      #   via design_conditions of the same name
    param_rules:                 # conditional defaults (first match wins per param)
    - when_node_enabled: eis     # node not in routing_switch.disabled_nodes
      set: {eis_margin_pct: 15}
    knobs:
      crop_strategy:
        condition_key: crop_strategy       # design_conditions key selecting the value
        default: mcsc_crop
        values:
          mcsc_crop: {}                    # no change (baseline)
          byrp_bcrop:
            derived:                       # ordered anchor rules (see below)
              bcrop_out: {from: sensor_full, scale: "(100 + eis_margin_pct) / (100 + sensor_margin_pct)",
                          align: 16, clamp_to: sensor_full}
            bindings: {rgbp: bcrop_out}    # node sim size <- anchor (overrides literals)
            variant_patch: {...}           # deep-merge; supports $unset / $append

Derived anchor rule keys: ``from`` (anchor), ``scale`` / ``scale_x`` / ``scale_y``
(number or arithmetic expression over params), ``align`` / ``align_x`` / ``align_y`` (ceil to multiple),
``round`` (``ceil`` | ``nearest``, default nearest when align==1), ``clamp_to`` (anchor).
When a variant selects a non-default value, the effective params are written to
its ``design_conditions`` (setdefault) so the DB records what the sizes were
derived from. Default values leave the variant untouched (baseline lossless).
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from scenario_db.authoring.errors import AuthoringError
from scenario_db.authoring.patch import deep_merge

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class KnobError(AuthoringError):
    pass


def eval_expr(expr: Any, params: dict[str, Any]) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in params:
                raise KnobError(f"unknown parameter '{node.id}' in '{expr}'")
            return float(params[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        raise KnobError(f"unsupported expression '{expr}'")

    return ev(ast.parse(str(expr), mode="eval"))


def parse_size(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or "x" not in value:
        return None
    w, _, h = value.partition("x")
    try:
        return int(w), int(h)
    except ValueError:
        return None


def _round(value: float, align: int, mode: str) -> int:
    if align > 1:
        return int(math.ceil(value / align - 1e-9) * align)
    if mode == "ceil":
        return int(math.ceil(value - 1e-9))
    return int(round(value))


def compute_anchor(rule: dict, anchors: dict[str, str], params: dict[str, Any], name: str) -> str:
    src = parse_size(anchors.get(rule["from"]))
    if src is None:
        raise KnobError(f"anchor '{name}': source '{rule['from']}' unresolved")
    sx = eval_expr(rule.get("scale_x", rule.get("scale", 1.0)), params)
    sy = eval_expr(rule.get("scale_y", rule.get("scale", 1.0)), params)
    ax = int(rule.get("align_x", rule.get("align", 1)))
    ay = int(rule.get("align_y", rule.get("align", 1)))
    mode = rule.get("round", "nearest")
    w, h = _round(src[0] * sx, ax, mode), _round(src[1] * sy, ay, mode)
    if rule.get("clamp_to"):
        cap = parse_size(anchors.get(rule["clamp_to"]))
        if cap:
            w, h = min(w, cap[0]), min(h, cap[1])
    return f"{w}x{h}"


def _match(variant: dict, rule: dict) -> bool:
    node = rule.get("when_node_enabled")
    if node:
        disabled = (variant.get("routing_switch") or {}).get("disabled_nodes") or []
        if node in disabled:
            return False
    for key, want in (rule.get("when") or {}).items():
        have = (variant.get("design_conditions") or {}).get(key)
        if isinstance(want, list) and have not in want:
            return False
        if not isinstance(want, list) and have != want:
            return False
    return True


def variant_params(spec: dict, variant: dict) -> dict[str, Any]:
    params = dict(spec.get("params") or {})
    fixed: set[str] = set()
    for rule in spec.get("param_rules") or []:
        if _match(variant, rule):
            for k, v in (rule.get("set") or {}).items():
                if k not in fixed:
                    params[k] = v
                    fixed.add(k)
    conds = variant.get("design_conditions") or {}
    for k in list(params):
        if k in conds:
            params[k] = conds[k]
    return params


def selected_values(spec: dict, variant: dict) -> dict[str, str]:
    conds = variant.get("design_conditions") or {}
    out = {}
    for name, knob in (spec.get("knobs") or {}).items():
        key = knob.get("condition_key", name)
        value = conds.get(key, knob.get("default"))
        if value not in (knob.get("values") or {}):
            raise KnobError(f"variant '{variant['id']}': knob '{name}' value '{value}' not in "
                            f"{sorted(knob.get('values') or {})}")
        out[name] = value
    return out


def knob_bound_nodes(spec: dict, variant: dict) -> set[str]:
    """Nodes whose sim size a knob value of this variant will overwrite."""
    if not spec:
        return set()
    nodes: set[str] = set()
    for name, value in selected_values(spec, variant).items():
        nodes |= set(((spec["knobs"][name]["values"][value]) or {}).get("bindings") or {})
    return nodes


def derived_in_dependency_order(derived: dict[str, dict]) -> list[tuple[str, dict]]:
    """Derived anchors ordered so every ``from`` / ``clamp_to`` anchor of the same knob value
    is computed first (a spec read back from JSONB loses the authored key order)."""
    pending = dict(derived)
    out: list[tuple[str, dict]] = []
    while pending:
        ready = [n for n, r in pending.items()
                 if not ({r.get("from"), r.get("clamp_to")} & (set(pending) - {n}))]
        if not ready:
            raise KnobError(f"derived anchors form a cycle: {sorted(pending)}")
        for n in sorted(ready, key=list(pending).index):
            out.append((n, pending.pop(n)))
    return out


def apply_knobs(base_anchors: dict[str, str], variant: dict, spec: dict) -> dict[str, Any]:
    """Apply selected knob values to one expanded variant (in place). Returns a trace."""
    if not spec or not spec.get("knobs"):
        return {}
    params = variant_params(spec, variant)
    trace: dict[str, Any] = {"values": {}, "params": params}
    selected = selected_values(spec, variant)
    if any(v != spec["knobs"][n].get("default") for n, v in selected.items()):
        conds = variant.setdefault("design_conditions", {})
        for k, v in params.items():
            conds.setdefault(k, v)
    for name, value in selected.items():
        effect = spec["knobs"][name]["values"][value] or {}
        trace["values"][name] = value
        if not effect:
            continue
        if effect.get("variant_patch"):
            patched = deep_merge(variant, effect["variant_patch"])
            variant.clear()
            variant.update(patched)
        for anchor, rule in derived_in_dependency_order(effect.get("derived") or {}):
            anchors = dict(base_anchors)
            anchors.update(variant.get("size_overrides") or {})
            variant.setdefault("size_overrides", {})[anchor] = compute_anchor(rule, anchors, params, anchor)
        if effect.get("bindings"):
            anchors = dict(base_anchors)
            anchors.update(variant.get("size_overrides") or {})
            for node, anchor in effect["bindings"].items():
                cfg = (variant.get("node_configs") or {}).get(node)
                if not isinstance(cfg, dict) or not isinstance(cfg.get("sim"), dict):
                    continue
                wh = parse_size(anchors.get(anchor))
                if wh is None:
                    raise KnobError(f"variant '{variant['id']}': knob anchor '{anchor}' unresolved")
                cfg["sim"]["width"], cfg["sim"]["height"] = wh
    return trace
