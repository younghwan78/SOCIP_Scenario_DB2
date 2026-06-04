from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse, SimulationReadinessResponse
from scenario_db.db.models.capability import SocDvfsTable
from scenario_db.db.repositories.evidence import (
    get_simulation_evidence_by_params_hash,
    upsert_simulation_evidence,
)
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.models import DVFSTable
from scenario_db.sim.readiness import check_simulation_readiness
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation


def run_simulation_request(db: Session, request: SimulateRequest) -> SimulateRunResponse:
    try:
        graph = load_canonical_graph(db, request.scenario_id, request.variant_id)
        inputs = build_simulation_inputs(graph, request.config)
        dvfs_tables, execution_context = _resolve_dvfs_tables(db, graph, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    hash_value = _request_hash(
        inputs,
        request,
        dvfs_tables=dvfs_tables,
        execution_context=execution_context,
    )
    if not request.force:
        cached = get_simulation_evidence_by_params_hash(
            db,
            scenario_ref=request.scenario_id,
            variant_ref=request.variant_id,
            params_hash=hash_value,
        )
        cache_has_required_trace = (
            cached is not None
            and (not request.config.debug_trace or bool(cached.calculation_trace))
        )
        if cached is not None and cache_has_required_trace:
            return SimulateRunResponse(
                evidence_id=cached.id,
                status="completed",
                cached=True,
                params_hash=hash_value,
                warnings=list(inputs.warnings),
                kpi=cached.kpi or {},
                result=None,
                evidence=EvidenceResponse.model_validate(cached).model_dump(mode="json"),
                persisted=True,
            )

    result = run_simulation(inputs, dvfs_tables=dvfs_tables)
    evidence = build_simulation_evidence(
        result,
        execution_context=execution_context,
        project_ref=inputs.project_ref,
        params_hash=hash_value,
    )
    if request.persist:
        upsert_simulation_evidence(db, evidence)
        db.commit()

    return SimulateRunResponse(
        evidence_id=evidence.id,
        status="completed",
        cached=False,
        params_hash=hash_value,
        warnings=result.warnings,
        kpi=evidence.kpi,
        result=result,
        evidence=_simulation_evidence_dict(evidence),
        persisted=request.persist,
    )


def _resolve_dvfs_tables(
    db: Session,
    graph,
    request: SimulateRequest,
) -> tuple[dict[str, DVFSTable], ExecutionContext]:
    if request.dvfs_tables and (request.dvfs_table_ref or request.dvfs_version is not None):
        raise HTTPException(
            status_code=422,
            detail="dvfs_tables cannot be combined with dvfs_table_ref or dvfs_version",
        )
    if request.dvfs_tables:
        return request.dvfs_tables, request.execution_context

    row = None
    if request.dvfs_table_ref:
        row = db.query(SocDvfsTable).filter_by(id=str(request.dvfs_table_ref)).one_or_none()
    elif request.dvfs_version is not None:
        soc_ref = request.soc_ref or _graph_soc_ref(graph)
        if not soc_ref:
            raise HTTPException(
                status_code=422,
                detail="soc_ref is required when selecting a DVFS table by dvfs_version",
            )
        row = (
            db.query(SocDvfsTable)
            .filter_by(soc_ref=str(soc_ref), dvfs_version=request.dvfs_version)
            .one_or_none()
        )

    if row is None:
        if request.dvfs_table_ref:
            raise HTTPException(status_code=404, detail=f"DVFS table not found: {request.dvfs_table_ref}")
        if request.dvfs_version is not None:
            soc_ref = request.soc_ref or _graph_soc_ref(graph)
            raise HTTPException(
                status_code=404,
                detail=f"DVFS table not found for soc_ref={soc_ref} dvfs_version={request.dvfs_version}",
            )
        return request.dvfs_tables, request.execution_context

    graph_soc_ref = _graph_soc_ref(graph)
    if graph_soc_ref and str(row.soc_ref) != str(graph_soc_ref):
        raise HTTPException(
            status_code=422,
            detail=f"DVFS table {row.id} belongs to {row.soc_ref}, not {graph_soc_ref}",
        )
    if request.soc_ref and str(row.soc_ref) != str(request.soc_ref):
        raise HTTPException(
            status_code=422,
            detail=f"DVFS table {row.id} belongs to {row.soc_ref}, not {request.soc_ref}",
        )

    execution_context = request.execution_context.model_copy(
        update={
            "evt_hint": row.evt_hint,
            "dvfs_table_ref": row.id,
            "dvfs_version": row.dvfs_version,
            "dvfs_soc_ref": row.soc_ref,
        },
    )
    return _dvfs_tables_from_row(row), execution_context


def _dvfs_tables_from_row(row: SocDvfsTable) -> dict[str, DVFSTable]:
    return {
        key: DVFSTable.model_validate(value)
        for key, value in (row.domains or {}).items()
    }


def _graph_soc_ref(graph) -> str | None:
    soc = getattr(graph, "soc", None)
    if soc is not None and getattr(soc, "id", None):
        return str(soc.id)
    project = getattr(graph, "project", None)
    if project is None:
        return None
    metadata = getattr(project, "metadata_", None) or {}
    globals_ = getattr(project, "globals_", None) or {}
    return metadata.get("soc_ref") or globals_.get("soc_ref")


def check_simulation_readiness_request(
    db: Session,
    scenario_id: str,
    variant_id: str,
) -> SimulationReadinessResponse:
    try:
        graph = load_canonical_graph(db, scenario_id, variant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SimulationReadinessResponse.model_validate(check_simulation_readiness(graph))


def _request_hash(
    inputs,
    request: SimulateRequest,
    *,
    dvfs_tables: dict[str, DVFSTable] | None = None,
    execution_context: ExecutionContext | None = None,
) -> str:
    effective_context = execution_context or request.execution_context
    effective_dvfs_tables = dvfs_tables if dvfs_tables is not None else request.dvfs_tables
    payload = {
        "inputs_hash": params_hash(inputs),
        "execution_context": effective_context.model_dump(
            mode="json",
            exclude_none=True,
        ),
        "config": request.config.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"debug_trace", "debug_trace_level"},
        ),
        "dvfs_selector": {
            "dvfs_table_ref": request.dvfs_table_ref,
            "soc_ref": request.soc_ref,
            "dvfs_version": request.dvfs_version,
        },
        "dvfs_tables": {
            key: value.model_dump(mode="json", exclude_none=True)
            for key, value in effective_dvfs_tables.items()
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _simulation_evidence_dict(evidence) -> dict:
    resolution_result = (
        evidence.resolution_result.model_dump(mode="json", exclude_none=True)
        if evidence.resolution_result else None
    )
    return {
        "id": evidence.id,
        "schema_version": evidence.schema_version,
        "kind": evidence.kind,
        "scenario_ref": evidence.scenario_ref,
        "variant_ref": evidence.variant_ref,
        "sw_baseline_ref": str(evidence.execution_context.sw_baseline_ref),
        "execution_context": evidence.execution_context.model_dump(mode="json", exclude_none=True),
        "sweep_context": evidence.sweep_context.model_dump(mode="json", exclude_none=True) if evidence.sweep_context else None,
        "resolution_result": resolution_result,
        "overall_feasibility": (
            str(evidence.resolution_result.overall_feasibility)
            if evidence.resolution_result else None
        ),
        "aggregation": evidence.aggregation.model_dump(mode="json", exclude_none=True),
        "kpi": dict(evidence.kpi),
        "run_info": evidence.run.model_dump(mode="json", exclude_none=True),
        "ip_breakdown": [item.model_dump(mode="json", exclude_none=True) for item in evidence.ip_breakdown],
        "dma_breakdown": [item.model_dump(mode="json", exclude_none=True) for item in evidence.dma_breakdown],
        "timing_breakdown": [item.model_dump(mode="json", exclude_none=True) for item in evidence.timing_breakdown],
        "dvfs_breakdown": [item.model_dump(mode="json", exclude_none=True) for item in evidence.dvfs_breakdown],
        "timeline_events": [item.model_dump(mode="json", exclude_none=True) for item in evidence.timeline_events],
        "external_devices": list(evidence.external_devices or []),
        "topology_order": list(evidence.topology_order or []),
        "vdd_power": evidence.vdd_power or {},
        "calculation_trace": evidence.calculation_trace,
        "params_hash": evidence.params_hash,
        "artifacts": [item.model_dump(mode="json", exclude_none=True) for item in evidence.artifacts],
    }
