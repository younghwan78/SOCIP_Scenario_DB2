"""Bounded OFAT exploration of a resolved DB scenario; baseline is never mutated."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
from typing import Literal

from pydantic import Field, model_validator

from scenario_db.models.common import BaseScenarioModel
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSTable, SimulationRunConfig
from scenario_db.sim.runner import run_simulation
from scenario_db.sim.resource_limits import DEFAULT_MAX_SWEEP_CASES


class ScenarioAxis(BaseScenarioModel):
    target: Literal['sw_margin', 'node_clock_mhz']
    node_id: str | None = None
    values: list[float] = Field(min_length=1, max_length=499)

    @model_validator(mode='after')
    def valid(self):
        import math
        if any(not math.isfinite(v) or v <= 0 for v in self.values):
            raise ValueError('axis values must be finite and positive')
        if (self.target == 'node_clock_mhz') != bool(self.node_id):
            raise ValueError('only node_clock_mhz requires node_id')
        return self


class ScenarioExplorationRequest(BaseScenarioModel):
    scenario_id: str
    variant_id: str
    project_ref: str
    axes: list[ScenarioAxis] = Field(default_factory=list)
    config: SimulationRunConfig = Field(default_factory=SimulationRunConfig)
    dvfs_tables: dict[str, DVFSTable] = Field(default_factory=dict)
    include_results: bool = False


def preview_scenario(graph, request: ScenarioExplorationRequest, *, max_cases=DEFAULT_MAX_SWEEP_CASES) -> dict:
    if graph.scenario.project_ref != request.project_ref:
        raise ValueError('scenario exploration project mismatch')
    if 1 + sum(len(a.values) for a in request.axes) > max_cases:
        raise ValueError(f'scenario exploration exceeds {max_cases} cases including baseline')
    if request.config.timing_profile is not None and request.axes:
        raise ValueError('measured timing replay cannot be extrapolated across architecture axes')
    specs = [(None, None)] + [(a, value) for a in request.axes for value in a.values]
    cases = []
    for index, (axis, value) in enumerate(specs):
        variant = deepcopy(graph.variant)
        config = request.config.model_copy(deep=True)
        candidate = replace(graph, variant=variant)
        if axis:
            if axis.target == 'node_clock_mhz':
                if candidate.node_by_id(axis.node_id) is None:
                    raise ValueError(f'unknown node: {axis.node_id}')
                variant.node_configs = deepcopy(variant.node_configs or {})
                node = variant.node_configs.setdefault(axis.node_id, {})
                node.setdefault('sim', {})['manual_clock_mhz'] = value
            else:
                setattr(config, axis.target, value)
                for node in candidate.pipeline_nodes:
                    variant.node_configs = variant.node_configs or {}
                    variant.node_configs.setdefault(node['id'], {}).setdefault('sim', {})['sw_margin'] = value
        if config.sw_timing_projection is not None:
            from scenario_db.sim.measured_timing import baseline_fingerprint
            if index == 0 and config.sw_timing_projection.target_model_fingerprint != baseline_fingerprint(graph):
                raise ValueError("projection target baseline changed")
            # Rebind only the bounded candidate derived from the verified baseline.
            config.sw_timing_projection = config.sw_timing_projection.model_copy(update={
                "target_model_fingerprint": baseline_fingerprint(candidate)})
        inputs = build_simulation_inputs(candidate, config)
        result = run_simulation(inputs, dvfs_tables=request.dvfs_tables)
        missing = sorted({w.node_id for w in inputs.workloads if w.sim_params.unit_power_mw_mp <= 0}
                         | {str(n['id']) for n in candidate.pipeline_nodes if n.get('ip_ref') not in candidate.ip_catalog})
        # CPU active energy and external-device power are not modeled in this engine.
        if inputs.sw_task_timing:
            missing.append('cpu_active_energy')
        if inputs.external_devices:
            missing.append('external_devices')
        metrics = dict(known_power_mw=result.total_power_mw, total_power_mw=None if missing else result.total_power_mw,
                       total_bw_mbs=result.bw_total_mbs, hw_time_max_ms=result.hw_time_max_ms,
                       timeline_end_ms=result.timeline_end_ms)
        cases.append(dict(case_id='baseline' if index == 0 else f'case-{index}',
                          axis=axis.model_dump() if axis else None, value=value,
                          input_hash=hashlib.sha256(inputs.model_dump_json().encode()).hexdigest(),
                          feasible=result.feasible, missing_power_domains=missing,
                          required_clocks_mhz={key: value.required_clock_mhz for key, value in result.resolved.items()},
                          set_clocks_mhz={key: value.set_clock_mhz for key, value in result.resolved.items()},
                          optimization_eligible=result.feasible and not missing,
                          metrics=metrics, warnings=result.warnings,
                          result=result.model_dump(mode='json') if request.include_results else None))
    baseline = cases[0]['metrics']
    for case in cases:
        case['delta_from_baseline'] = {k:v-baseline[k] for k,v in case['metrics'].items()
                                       if v is not None and baseline[k] is not None}
    return dict(persisted=False, strategy='one_factor_at_a_time', baseline_case_id='baseline', cases=cases)
