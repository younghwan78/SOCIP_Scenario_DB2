"""Resolve model selection and load bounded inputs for read-only analyses.

Selection is separate from graph loading so callers can reject a resolved model
before loading it, and keep profile failures fatal while collecting per-variant
graph failures. This module does not apply throughput/CPU policies or persist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.db.models.capability import SocDvfsTable
from scenario_db.db.repositories.scenario_graph import CanonicalScenarioGraph, load_canonical_graph
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSTable
from scenario_db.sim.service import (
    _apply_config_profile,
    _check_power_params_scope,
    _dvfs_tables_from_row,
    _enforce_input_limits,
    _graph_soc_ref,
    _resolve_dvfs_tables,
)


@dataclass(frozen=True)
class AnalysisInputs:
    graph: CanonicalScenarioGraph
    tables: dict[str, DVFSTable]
    dvfs_table_ref: str | None


@dataclass(frozen=True)
class AnalysisSelection:
    request: SimulateRequest
    config_profile_ref: str | None
    use_default_dvfs: bool

    def load(self, db: Session) -> AnalysisInputs:
        """Load this resolved selection; never mutate the caller's request."""
        request = self.request
        graph = load_canonical_graph(db, request.scenario_id, request.variant_id)
        soc_ref = _graph_soc_ref(graph)
        if request.soc_ref and soc_ref and str(request.soc_ref) != str(soc_ref):
            raise ValueError("soc_ref does not match the scenario project")
        if request.config.sw_timing_projection is not None:
            from scenario_db.sim.sw_projection import verify_projection

            verify_projection(db, graph, request.config.sw_timing_projection)
        if request.config.timing_profile is not None:
            raise ValueError("measured timing replay is not supported; use sw_timing_projection")
        from scenario_db.sim.sensor_projection import resolve_sensor_modes

        graph = resolve_sensor_modes(db, graph, request.config)
        _check_power_params_scope(request.config, graph)
        _enforce_input_limits(build_simulation_inputs(graph, request.config))
        tables, context = _resolve_dvfs_tables(db, graph, request)
        ref = context.dvfs_table_ref
        if not tables and self.use_default_dvfs:
            soc = request.soc_ref or _graph_soc_ref(graph)
            row = None
            if soc:
                row = (
                    db.query(SocDvfsTable)
                    .filter_by(soc_ref=str(soc))
                    .order_by(SocDvfsTable.dvfs_version.desc())
                    .first()
                )
            if row is not None:
                tables, ref = _dvfs_tables_from_row(row), str(row.id)
        return AnalysisInputs(graph, tables, ref)


def resolve_analysis_selection(
    db: Session, request: Any, variant_id: str | None = None
) -> AnalysisSelection:
    """Resolve basis/profile precedence on a detached analysis request."""
    resolved = SimulateRequest(
        scenario_id=request.scenario_id,
        variant_id=variant_id if variant_id is not None else request.variant_id,
        execution_context=ExecutionContext(
            silicon_rev="analysis", sw_baseline_ref="sw-timing-budget", thermal="n/a"
        ),
        config=request.config.model_copy(deep=True),
        config_profile_ref=request.config_profile_ref,
        dvfs_tables={key: table.model_copy(deep=True) for key, table in request.dvfs_tables.items()},
        dvfs_table_ref=request.dvfs_table_ref,
        soc_ref=request.soc_ref,
        dvfs_version=request.dvfs_version,
        basis_ref=getattr(request, "basis_ref", None),
        basis_overrides=list(getattr(request, "basis_overrides", None) or []),
    )
    profile = _apply_config_profile(db, resolved)
    return AnalysisSelection(resolved, profile, request.use_default_dvfs)
