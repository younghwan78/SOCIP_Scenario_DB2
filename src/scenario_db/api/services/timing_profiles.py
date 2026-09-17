"""Read-only profile preparation from DB measurement and resolved baseline."""
from __future__ import annotations

from typing import Literal
from pydantic import Field

from scenario_db.models.common import BaseScenarioModel
from scenario_db.models.evidence.measurement import MeasurementEvidence
from scenario_db.meas_import.timing_profile import build_profile
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import SimulationRunConfig
from scenario_db.sim.measured_timing import baseline_fingerprint


class TimingProfileRequest(BaseScenarioModel):
    profile_id: str = Field(min_length=1, max_length=160)
    revision: int = Field(default=1, ge=1)
    statistic: Literal['min', 'mean', 'max'] = 'mean'
    task_mapping: dict[str, str] = Field(min_length=1, max_length=1000)


def prepare_timing_profile(db, evidence_id: str, request: TimingProfileRequest):
    row = db.get(Evidence, evidence_id)
    if row is None:
        raise LookupError('measurement evidence not found')
    if row.kind != 'evidence.measurement':
        raise ValueError('timing profiles require measurement evidence')
    evidence = measurement_from_row(row)
    graph = load_canonical_graph(db, row.scenario_ref, row.variant_ref)
    if row.project_ref != graph.scenario.project_ref:
        raise ValueError('measurement project differs from scenario owner')
    profile = build_profile(evidence, evidence_sha256=row.yaml_sha256,
                            design_conditions=graph.variant.design_conditions or {},
                            baseline_sha256=baseline_fingerprint(graph), **request.model_dump())
    # Check active/collapsed tasks and edge anchors now, before offering download.
    build_simulation_inputs(graph, SimulationRunConfig(timing_profile=profile))
    return profile


def measurement_from_row(row: Evidence) -> MeasurementEvidence:
    raw = {key:getattr(row,key) for key in MeasurementEvidence.model_fields
           if hasattr(row,key) and getattr(row,key) is not None}
    if row.measured_at:
        raw['measured_at'] = row.measured_at.isoformat()
    return MeasurementEvidence.model_validate(raw)
