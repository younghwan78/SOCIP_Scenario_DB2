from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.schemas.evidence import EvidenceResponse
from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse, SimulationReadinessResponse
from scenario_db.db.repositories.evidence import (
    get_simulation_evidence_by_params_hash,
    upsert_simulation_evidence,
)
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.readiness import check_simulation_readiness
from scenario_db.sim.runner import build_simulation_evidence, params_hash, run_simulation


def run_simulation_request(db: Session, request: SimulateRequest) -> SimulateRunResponse:
    try:
        graph = load_canonical_graph(db, request.scenario_id, request.variant_id)
        inputs = build_simulation_inputs(graph, request.config)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    hash_value = _request_hash(inputs, request)
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

    result = run_simulation(inputs, dvfs_tables=request.dvfs_tables)
    evidence = build_simulation_evidence(
        result,
        execution_context=request.execution_context,
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


def _request_hash(inputs, request: SimulateRequest) -> str:
    payload = {
        "inputs_hash": params_hash(inputs),
        "execution_context": request.execution_context.model_dump(
            mode="json",
            exclude_none=True,
        ),
        "config": request.config.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"debug_trace", "debug_trace_level"},
        ),
        "dvfs_tables": {
            key: value.model_dump(mode="json", exclude_none=True)
            for key, value in request.dvfs_tables.items()
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
