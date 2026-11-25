"""R-1 / M-1: the scenario judgement contract and the judgement rate.

Below adapter and timing_budget (models only), so both can read the contract without a circular import.

Rate order: the request ``config.fps`` > ``pipeline.judgement.rate`` > ``design_conditions.fps`` > 30.
``fps_source`` is reported only when the scenario declares a rate, so undeclared reports keep their shape.
"""

from __future__ import annotations

import math
from typing import Any

DEFAULT_FPS = 30.0


def judgement_contract(graph):
    """The scenario's declared judgement contract (``pipeline.judgement``), or None (name rules)."""
    from scenario_db.models.definition.usecase import JudgementContract

    raw = (getattr(graph.scenario, "pipeline", None) or {}).get("judgement")
    return JudgementContract.model_validate(raw) if raw else None


def _positive(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"judgement.rate: {what} = {value!r} is not a number") from None
    if not math.isfinite(out) or out <= 0:
        raise ValueError(f"judgement.rate: {what} = {value!r} must be a finite positive rate")
    return out


def declared_rate(graph) -> tuple[float, str] | None:
    """The rate the contract declares, with its source; None when the scenario declares none."""
    contract = judgement_contract(graph)
    rate = contract.rate if contract is not None else None
    if rate is None:
        return None
    if rate.hz is not None:
        return _positive(rate.hz, "hz"), "contract.hz"
    if rate.condition is not None:
        value = (graph.variant.design_conditions or {}).get(rate.condition)
        if value is None:
            raise ValueError(f"judgement.rate: design_conditions.{rate.condition} missing in variant {graph.variant_id}")
        return _positive(value, f"design_conditions.{rate.condition}"), f"contract.condition:{rate.condition}"
    sim = ((graph.variant.node_configs or {}).get(rate.node) or {}).get("sim") or {}
    if not isinstance(sim, dict) or sim.get("fps") is None:
        raise ValueError(f"judgement.rate: node {rate.node} has no sim.fps in variant {graph.variant_id}")
    return _positive(sim["fps"], f"{rate.node}.sim.fps"), f"contract.node:{rate.node}"


def rate_and_source(graph, config=None) -> tuple[float, str | None]:
    """The judgement rate (Hz) and its source; the source is None when the scenario declares no rate."""
    requested = getattr(config, "fps", None) if config is not None else None
    declared = declared_rate(graph)
    if requested is not None:
        return float(requested), ("request" if declared is not None else None)
    if declared is not None:
        return declared
    design = graph.variant.design_conditions or {}
    return float(design.get("fps") or DEFAULT_FPS), None


def variant_rate(graph) -> float:
    """The scenario rate without a request (declared rate, else ``design_conditions.fps``, else 30)."""
    return rate_and_source(graph, None)[0]
