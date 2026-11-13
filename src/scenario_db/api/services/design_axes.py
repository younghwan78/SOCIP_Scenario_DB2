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
from math import prod
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


def build_design_plan(graph, config, levers: list[LeverAxis], prepare_sensor=None, *,
                      search: str = "exhaustive", max_sets: int = 64) -> dict[str, Any]:
    """The lever-axis plan of one variant.

    ``dimensions`` = the axes as shown; ``sets`` = combinations with their changed ``graph`` / ``config``
    or the ``error`` that stopped the change on this variant; ``search`` = how the space is covered.

    ``search="exhaustive"`` (or a space that fits ``max_sets`` anyway): every combination that changes at
    least one lever. ``search="screen"`` on a larger space: ``sets`` holds each lever value on its own,
    and ``expand(results, errors)`` — called by the engine once those are explored — ranks the levers by
    the largest power change one of their values made and returns the combinations of the top levers,
    as many levers as ``max_sets`` still allows. A value that could not be applied on its own is not
    combined.
    """
    dims: list[dict[str, Any]] = []
    per_axis: list[list[tuple[dict[str, Any], str]]] = []
    for axis in levers:
        kind = CHANGE_KINDS[axis.lever]
        changes = axis_changes(axis)
        selector = _selector(changes[0])
        label = axis.label or (f"{kind.label} · {selector}" if selector else kind.label)
        texts = [_value_text(c) for c in changes]
        dims.append({"lever": axis.lever, "label": label, "selector": selector, "group": kind.group, "values": texts})
        per_axis.append([(c, f"{label} {text}") for c, text in zip(changes, texts)])
    plan: dict[str, Any] = {"dimensions": dims, "sets": [], "notes": []}
    try:
        targets = whatif_targets(graph, config, None)
    except (LookupError, ValueError) as exc:
        plan["notes"].append(f"lever targets unavailable for this variant: {str(exc)[:200]}")
        targets = None

    def make(chosen: list[tuple[dict[str, Any], str]]) -> dict[str, Any]:
        changes = [c for c, _ in chosen]
        items = [{"lever": c["target"], "label": text, "change": c, "iq": change_iq(c, targets)} for c, text in chosen]
        row: dict[str, Any] = {"key": " | ".join(_change_key(c) for c in changes), "items": items,
                               "iq": max((i["iq"] for i in items), key=lambda v: _IQ_ORDER.get(v, 0))}
        if targets is None:
            row["error"] = "lever targets unavailable for this variant"
            return row
        notes: list[str] = []
        try:
            row["graph"], row["config"], _ = apply_whatif_changes(
                graph, changes, config, None, notes, prepare_sensor=prepare_sensor, targets=targets)
            row["notes"] = notes
        except (LookupError, ValueError) as exc:
            row["error"] = str(exc)
        return row

    def combos(values: list[list[tuple[dict[str, Any], str]]], at_least: int):
        """Combinations over ``values`` (one list per axis, in axis order) that change ``at_least`` levers."""
        for combo in product(*[[None, *axis] for axis in values]):
            chosen = [c for c in combo if c is not None]
            if len(chosen) >= at_least:
                yield chosen

    alone = sum(len(axis) for axis in per_axis)
    full = prod(len(axis) + 1 for axis in per_axis) - 1
    report: dict[str, Any] = {"mode": "exhaustive", "full_factorial": full, "one_at_a_time": alone, "combined": full - alone}
    if search != "screen" or full <= max_sets:
        plan["sets"] = [make(chosen) for chosen in combos(per_axis, 1)]
        plan["search"] = report
        return plan

    plan["sets"] = [make([value]) for axis in per_axis for value in axis]
    unranked = [{"lever": d["lever"], "label": d["label"], "impact_mw": None, "impact_pct": None, "combined": False}
                for d in dims]
    plan["search"] = report | {"mode": "screened", "combined": 0, "ranking": unranked}

    def expand(results: list[dict[str, Any]], errors: list[dict[str, Any]]) -> dict[str, Any]:
        by_key = {r["key"]: r for r in results}
        # per axis: the values that could be explored on their own, and the largest change one of them made
        usable = [[v for v in axis if _change_key(v[0]) in by_key] for axis in per_axis]
        impact: list[tuple[float, float | None] | None] = []
        for axis in usable:
            rows = [by_key[_change_key(c)] for c, _ in axis]
            pct = [abs(r["raw_delta_pct"]) for r in rows if r.get("raw_delta_pct") is not None]
            impact.append((max(abs(r["raw_delta_mw"]) for r in rows), max(pct) if pct else None) if rows else None)
        ranked = sorted((i for i, v in enumerate(impact) if v is not None), key=lambda i: (-impact[i][0], i))  # type: ignore[index]
        budget, chosen = max_sets - alone, []
        for i in ranked:
            trial = [*chosen, i]
            if prod(len(usable[j]) + 1 for j in trial) - 1 - sum(len(usable[j]) for j in trial) > budget:
                break
            chosen = trial
        if len(chosen) < 2:
            chosen = []  # a combination needs two levers
        picked = [usable[i] if i in chosen else [] for i in range(len(per_axis))]
        sets = [make(c) for c in combos(picked, 2)] if chosen else []
        order = [*ranked, *[i for i, v in enumerate(impact) if v is None]]
        ranking = [{"lever": dims[i]["lever"], "label": dims[i]["label"],
                    "impact_mw": round(impact[i][0], 3) if impact[i] else None,  # type: ignore[index]
                    "impact_pct": round(impact[i][1], 2) if impact[i] and impact[i][1] is not None else None,  # type: ignore[index]
                    "combined": i in chosen} for i in order]
        return {"sets": sets, "search": plan["search"] | {"combined": len(sets), "ranking": ranking}}

    plan["expand"] = expand
    return plan


def needs_catalog(config) -> bool:
    """A config that pins a reviewed sensor binding: every changed copy must be re-validated against the
    sensor catalog, which needs the DB (``prepare_sensor``)."""
    return bool(getattr(config, "sensor_modes", None))


def explore_with_levers(graph, spec: ArchExplorationSpec, *, config, dvfs_tables, explore=explore_variant,
                        prepare_sensor=None) -> dict[str, Any]:
    """``explore_variant`` with the lever-axis plan of this variant; without lever axes the call is the
    plain one.

    The plan is built here, where the variant is explored (also inside a pool worker), so the changed
    graphs of all variants are never held, or pickled, at the same time. ``prepare_sensor`` = the
    catalog re-validation of a pinned sensor binding (see :func:`needs_catalog`); it needs the caller's
    DB session, so such a variant is explored in the caller's process."""
    if not spec.axes.levers:
        return explore(graph, spec, config=config, dvfs_tables=dvfs_tables)
    design = build_design_plan(graph, config, spec.axes.levers, prepare_sensor,
                               search=spec.axes.lever_search, max_sets=spec.axes.lever_max_sets)
    return explore(graph, spec, config=config, dvfs_tables=dvfs_tables, design=design)
