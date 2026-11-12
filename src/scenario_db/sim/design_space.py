"""Declarative design space of an architecture exploration.

A design space names what is explored — lever axes — next to the constraints and the objective.
The six axes of :class:`ExplorationAxes` are the *built-in* levers (the engine evaluates them);
the What-if change kinds are *re-simulation* levers and are listed in the catalog only until the
engine evaluates them as axes.

``design_space_from_spec`` is lossless and ``spec_from_design_space`` is its inverse, so a request
written either way runs the same engine with the same ``input_hash``:

    spec_from_design_space(design_space_from_spec(spec)) == spec

A design space written by hand explores exactly the axes it lists: a built-in lever that is left
out is held at its neutral value (the objective's SW statistic and growth, EIS auto, no DVFS raise,
no compression search, no power-option search).
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.arch_exploration import (
    ArchExplorationSpec,
    CompressionAxis,
    ExplorationAxes,
    ExplorationConstraints,
    ExplorationObjective,
    PowerOptionAxis,
)
from scenario_db.sim.timing_budget import TimingBudgetOptions

SCHEMA: Final = "sdb.designspace/1"


@dataclass(frozen=True)
class BuiltinLever:
    id: str
    label: str
    group: str        # same palette groups as the What-if levers, plus "sw"
    shape: str        # "choice" | "value" | "level"
    evaluation: str   # how one value is priced: timeline simulation / analytic on a slice / re-simulation
    unit: str
    description: str


BUILTIN_LEVERS: dict[str, BuiltinLever] = {lever.id: lever for lever in (
    BuiltinLever("sw_statistic", "SW 통계", "sw", "choice", "timeline", "",
                 "SW task runtime 통계 (min · mean · max). 값마다 timeline을 다시 계산"),
    BuiltinLever("sw_growth", "차기 SW 증가", "sw", "value", "timeline", "×",
                 "SW runtime 증가 배율. 값마다 timeline을 다시 계산"),
    BuiltinLever("eis", "EIS", "mode", "choice", "timeline", "",
                 "EIS 경로 (auto = variant 설정)"),
    BuiltinLever("dvfs_headroom", "DVFS headroom", "clock", "level", "analytic", "level",
                 "해석된 DVFS level에서 올려 보는 단계 수 (0 = 올리지 않음)"),
    BuiltinLever("buffer_compression", "Buffer 압축", "compression", "choice", "analytic", "",
                 "buffer별 SBWC lossless · lossy 조합 (절감 상위 buffer)"),
    BuiltinLever("power_options", "Power option", "mode", "choice", "resim", "",
                 "arch knob · IP mode 조합 (조합마다 재시뮬레이션)"),
)}

_COMPRESSION_PARAMS = ("ratio_overrides", "buffers", "include_unsupported", "require_declared",
                       "max_buffers", "min_saving_mbs")
_OPTION_KINDS = ("knob", "ip_mode")


class LeverAxis(BaseScenarioModel):
    """One explored lever: ``lever`` = a built-in lever id or a What-if change-kind target."""

    lever: str = Field(min_length=1, max_length=64)
    values: list[Any] = Field(default_factory=list, max_length=64)
    # lever settings that are not explored values (compression: buffer cap, ratios ...; a
    # re-simulation lever: its selector such as node_id)
    params: dict[str, Any] = Field(default_factory=dict)
    label: str | None = Field(default=None, max_length=120)


class EvaluationOptions(BaseScenarioModel):
    """How a case is evaluated and reported — the non-axis fields of the exploration spec."""

    timing: TimingBudgetOptions = Field(default_factory=TimingBudgetOptions)
    top_n: int = Field(default=5, ge=1, le=20)
    max_cases_per_variant: int = Field(default=200_000, ge=1, le=200_000)
    verify: bool = True
    verify_tolerance_pct: float = Field(default=0.5, gt=0, le=10)


class DesignSpace(BaseScenarioModel):
    schema_version: Literal["sdb.designspace/1"] = SCHEMA
    axes: list[LeverAxis] = Field(default_factory=list, max_length=32)
    constraints: ExplorationConstraints = Field(default_factory=ExplorationConstraints)
    objective: ExplorationObjective = Field(default_factory=ExplorationObjective)
    evaluation: EvaluationOptions = Field(default_factory=EvaluationOptions)

    @model_validator(mode="after")
    def _unique_builtin(self) -> DesignSpace:
        seen: set[str] = set()
        for axis in self.axes:
            if axis.lever in BUILTIN_LEVERS and axis.lever in seen:
                raise ValueError(f"lever {axis.lever} is listed more than once")
            seen.add(axis.lever)
        return self


def resim_axes(space: DesignSpace) -> list[LeverAxis]:
    """Axes the built-in engine axes cannot express (What-if change kinds)."""
    return [axis for axis in space.axes if axis.lever not in BUILTIN_LEVERS]


# --------------------------------------------------------------- spec -> design space
def design_space_from_spec(spec: ArchExplorationSpec) -> DesignSpace:
    """The spec as a design space; lossless (every built-in axis is listed, disabled ones marked)."""
    axes, comp, opts = spec.axes, spec.axes.compression, spec.axes.power_options
    comp_params: dict[str, Any] = {key: getattr(comp, key) for key in _COMPRESSION_PARAMS}
    opt_params: dict[str, Any] = {"max_sets": opts.max_sets}
    if not comp.enabled:
        comp_params["enabled"] = False
    if not opts.enabled:
        opt_params["enabled"] = False
    kinds = [kind for kind, on in zip(_OPTION_KINDS, (opts.include_knobs, opts.include_modes)) if on]
    return DesignSpace(
        axes=[
            LeverAxis(lever="sw_statistic", values=list(axes.statistics)),
            LeverAxis(lever="sw_growth", values=list(axes.runtime_scales)),
            LeverAxis(lever="eis", values=[axes.eis]),
            LeverAxis(lever="dvfs_headroom", values=list(range(axes.dvfs_headroom_levels + 1))),
            LeverAxis(lever="buffer_compression", values=list(comp.modes), params=comp_params),
            LeverAxis(lever="power_options", values=kinds, params=opt_params),
        ],
        constraints=spec.constraints,
        objective=spec.objective,
        evaluation=EvaluationOptions(
            timing=spec.timing, top_n=spec.top_n, max_cases_per_variant=spec.max_cases_per_variant,
            verify=spec.verify, verify_tolerance_pct=spec.verify_tolerance_pct),
    )


# --------------------------------------------------------------- design space -> spec
def _only(axis: LeverAxis, allowed: Collection[str]) -> None:
    extra = sorted(set(axis.params) - set(allowed))
    if extra:
        raise ValueError(f"lever {axis.lever}: unknown params {', '.join(extra)}")


def _headroom(axis: LeverAxis) -> int:
    _only(axis, ())
    values = axis.values
    if not values or any(isinstance(v, bool) or not isinstance(v, int) for v in values) \
            or sorted(values) != list(range(len(values))):
        raise ValueError("lever dvfs_headroom: values must be the raise steps 0..k (e.g. [0, 1])")
    return len(values) - 1


def _compression(axis: LeverAxis) -> CompressionAxis:
    _only(axis, (*_COMPRESSION_PARAMS, "enabled"))
    return CompressionAxis(modes=axis.values, **axis.params)


def _power_options(axis: LeverAxis) -> PowerOptionAxis:
    _only(axis, ("max_sets", "enabled"))
    unknown = sorted({str(v) for v in axis.values} - set(_OPTION_KINDS))
    if unknown or len(set(axis.values)) != len(axis.values):
        raise ValueError(f"lever power_options: values must be distinct items of {', '.join(_OPTION_KINDS)}")
    return PowerOptionAxis(include_knobs="knob" in axis.values, include_modes="ip_mode" in axis.values, **axis.params)


def spec_from_design_space(space: DesignSpace, *, resim_levers: Collection[str] = ()) -> ArchExplorationSpec:
    """The engine spec of a design space made of built-in levers.

    ``resim_levers`` = lever ids the catalog lists as re-simulation levers: such an axis is
    reported as not evaluated yet instead of unknown.
    """
    other = resim_axes(space)
    if other:
        names = sorted({axis.lever for axis in other})
        unknown = [name for name in names if name not in resim_levers]
        if unknown:
            raise ValueError(f"unknown lever: {', '.join(unknown)} (built-in: {', '.join(BUILTIN_LEVERS)})")
        raise ValueError(f"re-simulation lever axes are not evaluated by exploration yet: {', '.join(names)}")
    by_id = {axis.lever: axis for axis in space.axes}
    objective = space.objective
    fields: dict[str, Any] = {
        "statistics": [objective.statistic], "runtime_scales": [objective.runtime_scale], "eis": "auto",
        "dvfs_headroom_levels": 0, "compression": CompressionAxis(enabled=False),
        "power_options": PowerOptionAxis(enabled=False),
    }
    for lever, key in (("sw_statistic", "statistics"), ("sw_growth", "runtime_scales")):
        if lever in by_id:
            _only(by_id[lever], ())
            fields[key] = by_id[lever].values
    if "eis" in by_id:
        _only(by_id["eis"], ())
        if len(by_id["eis"].values) != 1:
            raise ValueError("lever eis: exactly one value (auto, on or off)")
        fields["eis"] = by_id["eis"].values[0]
    if "dvfs_headroom" in by_id:
        fields["dvfs_headroom_levels"] = _headroom(by_id["dvfs_headroom"])
    if "buffer_compression" in by_id:
        fields["compression"] = _compression(by_id["buffer_compression"])
    if "power_options" in by_id:
        fields["power_options"] = _power_options(by_id["power_options"])
    evaluation = space.evaluation
    return ArchExplorationSpec(
        axes=ExplorationAxes(**fields), constraints=space.constraints, objective=objective,
        timing=evaluation.timing, top_n=evaluation.top_n,
        max_cases_per_variant=evaluation.max_cases_per_variant, verify=evaluation.verify,
        verify_tolerance_pct=evaluation.verify_tolerance_pct,
    )


# --------------------------------------------------------------- catalog / stored runs
_SPEC_FIELDS = tuple(ArchExplorationSpec.model_fields)


def design_space_of_stored_spec(stored: dict[str, Any] | None) -> dict[str, Any] | None:
    """Design space of a persisted run spec (run metadata keys are ignored); ``None`` when the stored
    spec predates the current models and no longer validates."""
    try:
        spec = ArchExplorationSpec.model_validate({k: v for k, v in (stored or {}).items() if k in _SPEC_FIELDS})
        return design_space_from_spec(spec).model_dump(mode="json")
    except ValueError:
        return None


def builtin_catalog() -> list[dict[str, Any]]:
    """Catalog rows of the built-in levers, with the values the default spec explores."""
    default = {axis.lever: axis for axis in design_space_from_spec(ArchExplorationSpec()).axes}
    return [{
        "id": lever.id, "label": lever.label, "group": lever.group, "shape": lever.shape, "unit": lever.unit,
        "description": lever.description, "source": "builtin", "evaluation": lever.evaluation, "explorable": True,
        "default": {"values": default[lever.id].values, "params": default[lever.id].params},
    } for lever in BUILTIN_LEVERS.values()]
