"""Lever catalog of architecture exploration: built-in engine axes + the What-if change kinds."""
from __future__ import annotations

from typing import Any

from scenario_db.api.services.whatif_conditions import CHANGE_KINDS
from scenario_db.sim.design_space import SCHEMA, builtin_catalog


def lever_catalog() -> dict[str, Any]:
    """Every lever a design space can name. ``explorable`` = the exploration engine evaluates it as an
    axis today; the What-if change kinds are re-simulation levers, evaluated by What-if sweep only.
    Per-variant instances (which nodes, sizes, options) come from the What-if targets of that variant."""
    levers = builtin_catalog()
    levers += [{
        "id": kind.target, "label": kind.label, "group": kind.group, "shape": kind.shape, "unit": kind.unit,
        "description": kind.description, "source": "whatif", "evaluation": "resim", "explorable": False,
        "selector": kind.selector, "selector_optional": kind.selector_optional, "needs_param": kind.needs_param,
        "max_value": kind.max_value, "iq": kind.iq, "value_optional": kind.value_optional,
    } for kind in CHANGE_KINDS.values()]
    return {"schema_version": SCHEMA, "levers": levers}
