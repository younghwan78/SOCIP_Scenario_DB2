"""Re-simulation lever axes of an exploration: What-if change kinds turned into changed variants.

The exploration engine does not know how a lever rewrites a variant; the What-if condition registry
does. This module turns ``spec.axes.levers`` into the plan the engine explores: every combination
of the axis values (each axis may also keep its current value) applied to a detached copy of the
variant graph. A combination that cannot be applied to this variant (the node is not in its
pipeline, the size is not supported ...) is kept with its error, so one run can cover variants
that differ in which levers they have.
"""
from __future__ import annotations

import json
from itertools import product
from typing import Any

from pydantic import ValidationError

from scenario_db.api.schemas.scenario_whatif import WhatIfChange
from scenario_db.api.services.whatif_conditions import CHANGE_KINDS, apply_whatif_changes, change_iq, whatif_targets
from scenario_db.sim.arch_exploration import ArchExplorationSpec, LeverAxis, explore_variant
from scenario_db.sim.design_space import BUILTIN_LEVERS

# Change kinds an axis may name. Left out on purpose: ``compression`` and ``dvfs_level`` (the built-in
# buffer_compression / dvfs_headroom levers search them per case), ``node_param`` (outside the power
# and clock model) and ``sensor_binding`` (a reviewed DT binding, prepared from the catalog per request).
EXPLORABLE_KINDS: tuple[str, ...] = (
    "output_size", "anchor_size", "node_size", "stream_size", "chain_size", "fps", "sensor_mode",
    "history_interval", "llc_alloc", "ip_mode", "power_knob", "node_clock_mhz",
)
_IQ_ORDER = {"neutral": 0, "eval": 1, "trade": 2}
_SELECTOR_KEYS = ("anchor_id", "node_id", "stream_id", "buffer_id", "param")


def _value_fields(lever: str, value: Any) -> dict[str, Any]:
    """One axis value as What-if change fields: a dict is taken as is, otherwise by the kind's shape."""
    if isinstance(value, dict):
        return dict(value)
    shape = CHANGE_KINDS[lever].shape
    if shape == "size" and isinstance(value, (list, tuple)) and len(value) == 2:
        return {"width": value[0], "height": value[1]}
    if shape == "value" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"value": value}
    if shape == "choice" and isinstance(value, str):
        return {"option": value}
    want = {"size": "[width, height]", "value": "a number", "choice": "an option id"}.get(shape, "a change object")
    raise ValueError(f"lever {lever}: value {value!r} must be {want} or a change object")


def axis_changes(axis: LeverAxis) -> list[dict[str, Any]]:
    """The What-if change of every value of one axis (validated like a What-if request)."""
    changes = []
    for value in axis.values:
        fields = _value_fields(axis.lever, value)
        clash = sorted(set(fields) & set(axis.params))
        if clash or "target" in fields or "target" in axis.params:
            raise ValueError(f"lever {axis.lever}: {', '.join(clash) or 'target'} is set twice (params and value)")
        try:
            change = WhatIfChange(target=axis.lever, **axis.params, **fields)
        except ValidationError as exc:
            raise ValueError(f"lever {axis.lever}: {exc.errors()[0]['msg']}") from exc
        except TypeError as exc:
            raise ValueError(f"lever {axis.lever}: {exc}") from exc
        changes.append(change.model_dump(mode="json", exclude_none=True))
    return changes


def validate_levers(levers: list[LeverAxis]) -> None:
    """Request-time check of the re-simulation axes: explorable kinds, well-formed values, one axis per instance."""
    seen: set[str] = set()
    for axis in levers:
        if axis.lever in BUILTIN_LEVERS:
            raise ValueError(f"lever {axis.lever} is a built-in axis; set it in the spec axes")
        if axis.lever not in CHANGE_KINDS:
            raise ValueError(f"unknown lever: {axis.lever}")
        if axis.lever not in EXPLORABLE_KINDS:
            raise ValueError(f"lever cannot be explored as an axis: {axis.lever}")
        changes = axis_changes(axis)
        keys = [_change_key(c) for c in changes]
        if len(set(keys)) != len(keys):
            raise ValueError(f"lever {axis.lever}: values must be distinct")
        instance = json.dumps([axis.lever, axis.params], sort_keys=True)
        if instance in seen:
            raise ValueError(f"lever {axis.lever} is listed more than once for the same target")
        seen.add(instance)


def _selector(change: dict[str, Any]) -> str | None:
    return next((str(change[k]) for k in _SELECTOR_KEYS if change.get(k) is not None), None)


def _value_text(change: dict[str, Any]) -> str:
    unit = CHANGE_KINDS[change["target"]].unit
    if "width" in change:
        op = f"{change['operation']} " if change.get("operation") else ""
        at = f" @({change.get('x', 0)},{change.get('y', 0)})" if change.get("x") is not None or change.get("y") is not None else ""
        port = f" port {change['port']}" if change.get("port") else ""
        return f"{op}{change['width']}x{change['height']}{at}{port}"
    if change.get("option") is not None:
        return str(change["option"]) + (f" ({change['value']:g})" if change.get("value") is not None else "")
    return f"{change['value']:g}{f' {unit}' if unit else ''}"


def _change_key(change: dict[str, Any]) -> str:
    selector = _selector(change)
    value = f"{change['width']}x{change['height']}" if "width" in change else change.get("option") or f"{change['value']:g}"
    extra = f"@{change['value']:g}" if "option" in change and change.get("value") is not None else ""
    op = f":{change['operation']}" if change.get("operation") else ""
    if change.get("x") is not None or change.get("y") is not None:
        extra += f"@({change.get('x', 0)},{change.get('y', 0)})"
    if change.get("port"):
        extra += f"@port:{change['port']}"
    return f"{change['target']}{f'[{selector}]' if selector else ''}{op}={value}{extra}"


def build_design_plan(graph, config, levers: list[LeverAxis], prepare_sensor=None) -> dict[str, Any]:
    """``dimensions`` (the axes as shown) and ``sets``: every combination that changes at least one lever,
    with its changed ``graph`` / ``config`` or the ``error`` that stopped it on this variant."""
    dims: list[dict[str, Any]] = []
    per_axis: list[list[tuple[dict[str, Any], str] | None]] = []
    for axis in levers:
        kind = CHANGE_KINDS[axis.lever]
        changes = axis_changes(axis)
        selector = _selector(changes[0])
        label = axis.label or (f"{kind.label} · {selector}" if selector else kind.label)
        texts = [_value_text(c) for c in changes]
        dims.append({"lever": axis.lever, "label": label, "selector": selector, "group": kind.group, "values": texts})
        per_axis.append([None, *[(c, f"{label} {text}") for c, text in zip(changes, texts)]])
    plan: dict[str, Any] = {"dimensions": dims, "sets": [], "notes": []}
    try:
        targets = whatif_targets(graph, config, None)
    except (LookupError, ValueError) as exc:
        plan["notes"].append(f"lever targets unavailable for this variant: {str(exc)[:200]}")
        targets = None
    for combo in product(*per_axis):
        chosen = [c for c in combo if c is not None]
        if not chosen:
            continue  # nothing changed = the variant itself
        changes = [c for c, _ in chosen]
        items = [{"lever": c["target"], "label": text, "change": c, "iq": change_iq(c, targets)} for c, text in chosen]
        key = " | ".join(_change_key(c) for c in changes)
        row: dict[str, Any] = {"key": key, "items": items,
                               "iq": max((i["iq"] for i in items), key=lambda v: _IQ_ORDER.get(v, 0))}
        if targets is None:
            row["error"] = "lever targets unavailable for this variant"
        else:
            notes: list[str] = []
            try:
                row["graph"], row["config"], _ = apply_whatif_changes(
                    graph, changes, config, None, notes, prepare_sensor=prepare_sensor, targets=targets)
                row["notes"] = notes
            except (LookupError, ValueError) as exc:
                row["error"] = str(exc)
        plan["sets"].append(row)
    return plan


def needs_catalog(config) -> bool:
    """A config that pins a reviewed sensor binding: every changed copy must be re-validated against the
    sensor catalog, which needs the DB (``prepare_sensor``)."""
    return bool(getattr(config, "sensor_modes", None))


def explore_with_levers(graph, spec: ArchExplorationSpec, *, config, dvfs_tables, explore=explore_variant,
                        design: dict[str, Any] | None = None) -> dict[str, Any]:
    """``explore_variant`` with the lever-axis plan of this variant; without lever axes the call is the
    plain one.

    The plan is normally built here, where the variant is explored (also inside a pool worker), so the
    changed graphs of all variants are never held, or pickled, at the same time. ``design`` = a plan the
    caller already built because it needed the DB (a pinned sensor binding, see :func:`needs_catalog`)."""
    if not spec.axes.levers:
        return explore(graph, spec, config=config, dvfs_tables=dvfs_tables)
    if design is None:
        design = build_design_plan(graph, config, spec.axes.levers)
    return explore(graph, spec, config=config, dvfs_tables=dvfs_tables, design=design)
