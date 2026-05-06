from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from scenario_db.api.schemas.simulation import SimulateRequest, SimulateRunResponse
from scenario_db.db.repositories.evidence import (
    get_simulation_evidence_by_params_hash,
    upsert_simulation_evidence,
)
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.sim.adapter import build_simulation_inputs
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
        if cached is not None:
            return SimulateRunResponse(
                evidence_id=cached.id,
                status="completed",
                cached=True,
                params_hash=hash_value,
                kpi=cached.kpi or {},
                result=None,
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
        kpi=evidence.kpi,
        result=result,
    )


def _request_hash(inputs, request: SimulateRequest) -> str:
    payload = {
        "inputs_hash": params_hash(inputs),
        "dvfs_tables": {
            key: value.model_dump(mode="json", exclude_none=True)
            for key, value in request.dvfs_tables.items()
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

