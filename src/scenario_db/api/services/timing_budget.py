"""Stage timing budget API service (read-only; never persists)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from scenario_db.api.schemas.simulation import SimulateRequest
from scenario_db.api.schemas.timing_budget import (
    TimingBudgetFleetRequest,
    TimingBudgetFleetResponse,
    TimingBudgetRequest,
    TimingBudgetResponse,
)
from scenario_db.db.models.capability import SocDvfsTable
from scenario_db.db.models.definition import ScenarioVariant
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.service import (
    _apply_config_profile,
    _dvfs_tables_from_row,
    _enforce_input_limits,
    _graph_soc_ref,
    _resolve_dvfs_tables,
)
from scenario_db.sim.timing_budget import (
    DERIVED_VARIANT_MARKERS,
    analyze_timing_budget,
    fleet_row,
)


def _shim(request, variant_id: str) -> SimulateRequest:
    return SimulateRequest(
        scenario_id=request.scenario_id,
        variant_id=variant_id,
        execution_context=ExecutionContext(
            silicon_rev="analysis", sw_baseline_ref="sw-timing-budget", thermal="n/a"
        ),
        config=request.config,
        config_profile_ref=request.config_profile_ref,
        dvfs_tables=request.dvfs_tables,
        dvfs_table_ref=request.dvfs_table_ref,
        soc_ref=request.soc_ref,
        dvfs_version=request.dvfs_version,
    )


def _load(db: Session, shim: SimulateRequest, use_default_dvfs: bool):
    graph = load_canonical_graph(db, shim.scenario_id, shim.variant_id)
    if shim.soc_ref and _graph_soc_ref(graph) and str(shim.soc_ref) != str(_graph_soc_ref(graph)):
        raise ValueError("soc_ref does not match the scenario project")
    if shim.config.sw_timing_projection is not None:
        from scenario_db.sim.sw_projection import verify_projection

        verify_projection(db, graph, shim.config.sw_timing_projection)
    if shim.config.timing_profile is not None:
        raise ValueError("measured timing replay is not supported; use sw_timing_projection")
    from scenario_db.sim.sensor_projection import resolve_sensor_modes

    graph = resolve_sensor_modes(db, graph, shim.config)
    _enforce_input_limits(build_simulation_inputs(graph, shim.config))
    tables, context = _resolve_dvfs_tables(db, graph, shim)
    ref = context.dvfs_table_ref
    if not tables and use_default_dvfs:
        soc = shim.soc_ref or _graph_soc_ref(graph)
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
    return graph, tables, ref


def analyze_timing_budget_request(
    db: Session, request: TimingBudgetRequest
) -> TimingBudgetResponse:
    shim = _shim(request, request.variant_id)
    profile = _apply_config_profile(db, shim)
    try:
        graph, tables, ref = _load(db, shim, request.use_default_dvfs)
        report = analyze_timing_budget(
            graph, request.options, config=shim.config, dvfs_tables=tables
        )
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    report["dvfs"]["table_ref"] = ref
    return TimingBudgetResponse(
        scenario_id=request.scenario_id,
        variant_id=request.variant_id,
        config_profile_ref=profile,
        dvfs_table_ref=ref,
        report=report,
    )


def analyze_timing_budget_fleet(
    db: Session, request: TimingBudgetFleetRequest
) -> TimingBudgetFleetResponse:
    ids = request.variant_ids
    if ids is None:
        rows = (
            db.query(ScenarioVariant.id, ScenarioVariant.derived_from_variant)
            .filter_by(scenario_id=request.scenario_id)
            .order_by(ScenarioVariant.id)
            .all()
        )
        ids = [r[0] for r in rows if request.include_derived or not r[1]]
        if not ids:
            raise NotFoundError(f"scenario has no variants: {request.scenario_id}")
        if not request.include_derived:
            ids = [i for i in ids if not any(m in i for m in DERIVED_VARIANT_MARKERS)]
    options = request.options.model_copy(update={"include_whatif": False})
    ids = list(dict.fromkeys(ids))
    if len(ids) > 200:
        raise UnprocessableError("fleet scope exceeds 200 variants; select a bounded subset")
    out, errors, ref, profile = [], [], None, None
    for variant_id in ids:
        shim = _shim(request, variant_id)
        profile = _apply_config_profile(db, shim)
        try:
            graph, tables, ref = _load(db, shim, request.use_default_dvfs)
            out.append(
                fleet_row(
                    analyze_timing_budget(graph, options, config=shim.config, dvfs_tables=tables)
                )
            )
        except (LookupError, ValueError) as exc:
            errors.append({"variant_id": variant_id, "error": str(exc)[:300]})
    return TimingBudgetFleetResponse(
        scenario_id=request.scenario_id,
        config_profile_ref=profile,
        dvfs_table_ref=ref,
        rows=out,
        errors=errors,
    )
