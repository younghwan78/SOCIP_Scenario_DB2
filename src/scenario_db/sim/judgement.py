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
    cfg = (graph.variant.node_configs or {}).get(rate.node)
    sim = (cfg.get("sim") if isinstance(cfg, dict) else None) or {}
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


def baseline_fps(graph) -> Any:
    """The rate a run without a request fps uses, for comparisons that used ``design_conditions.fps``
    (measured replay, sensor modes): the declared rate, else the stored ``design_conditions.fps`` (may be None)."""
    declared = declared_rate(graph)
    return declared[0] if declared is not None else (graph.variant.design_conditions or {}).get("fps")


def rate_issues(scenario_id: str, pipeline: dict | None, variants: list) -> tuple[list[str], list[str]]:
    """(errors, warnings) of a declared ``judgement.rate`` over the effective variants (inheritance and
    ``design_conditions_override`` applied), shared by authoring and the strict ETL.

    Errors: the rate does not resolve, or ``design_conditions.fps`` disagrees with it (the views and the
    measured replay still read that key). Warnings: a node repeats the rate in ``sim.fps`` /
    ``sim.domain_load.rate_hz`` (a rate-following node should leave it unset so a request fps moves it)."""
    from types import SimpleNamespace

    from pydantic import ValidationError

    from scenario_db.models.definition.usecase import JudgementContract

    raw = (pipeline or {}).get("judgement")
    if not isinstance(raw, dict) or raw.get("rate") is None:
        return [], []
    try:
        contract = JudgementContract.model_validate(raw)
    except ValidationError:
        return [], []          # the schema check reports it, with its file and field
    if contract.rate is None:
        return [], []
    from scenario_db.db.models.definition import ScenarioVariant
    from scenario_db.db.repositories.variant_resolution import resolve_variant_from_rows

    fields = set(ScenarioVariant.__table__.columns.keys())
    rows = {}
    for v in variants:          # compiled documents (authoring) or loaded rows (strict ETL)
        if isinstance(v, ScenarioVariant):
            rows[str(v.id)] = v
        elif isinstance(v, dict) and v.get("id"):
            rows[str(v["id"])] = ScenarioVariant(**{k: val for k, val in v.items() if k in fields},
                                                 scenario_id=scenario_id)
    errors: list[str] = []
    warnings: list[str] = []
    scenario = SimpleNamespace(pipeline={**(pipeline or {}), "judgement": raw})
    for vid in rows:
        try:
            variant = resolve_variant_from_rows(rows, scenario_id, vid)
        except Exception as exc:  # noqa: BLE001 - an inheritance error is reported by its own check
            errors.append(f"{scenario_id}/{vid}: variant does not resolve: {exc}")
            continue
        graph = SimpleNamespace(scenario=scenario, variant=variant, variant_id=vid)
        try:
            hz, _ = declared_rate(graph)  # type: ignore[misc]
        except ValueError as exc:
            errors.append(f"{scenario_id}/{vid}: {exc}")
            continue
        design = (variant.design_conditions or {}).get("fps")
        if design is not None:
            try:
                same = abs(float(design) - hz) < 1e-9
            except (TypeError, ValueError):
                same = False
            if not same:
                errors.append(f"{scenario_id}/{vid}: design_conditions.fps {design!r} disagrees with judgement.rate {hz:g}")
        for node_id, cfg in (variant.node_configs or {}).items():
            if node_id == contract.rate.node or not isinstance(cfg, dict) or not isinstance(cfg.get("sim"), dict):
                continue
            sim = cfg["sim"]
            load = sim.get("domain_load") if isinstance(sim.get("domain_load"), dict) else {}
            for key, pinned in (("sim.fps", sim.get("fps")), ("sim.domain_load.rate_hz", load.get("rate_hz"))):
                try:
                    repeated = pinned is not None and abs(float(pinned) - hz) < 1e-9
                except (TypeError, ValueError):
                    repeated = False
                if repeated:
                    warnings.append(f"{scenario_id}/{vid}: node '{node_id}' {key} {pinned} repeats judgement.rate "
                                    "(a rate-following node should leave it unset so a request fps moves it)")
    return errors, warnings
