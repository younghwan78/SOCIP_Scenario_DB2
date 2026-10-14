"""What-if planning, authoritative calculation, and private/shared frozen experiments."""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from scenario_db.api.schemas.scenario_whatif import WhatIfExperimentRequest, WhatIfPlanRequest, WhatIfPreviewRequest, WhatIfScope
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services.review_policy import apply_throughput, scenario_policy
from scenario_db.api.services.timing_budget import _load, _shim
from scenario_db.api.services.whatif_conditions import apply_whatif_changes, whatif_targets
from scenario_db.api.services.whatif_query import plan_query
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.whatif import WhatIfExperiment
from scenario_db.db.repositories.scenario_graph import load_canonical_graph
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.measured_timing import baseline_fingerprint
from scenario_db.sim.service import _apply_config_profile, _enforce_input_limits
from scenario_db.sim.timing_budget import analyze_timing_budget

ENGINE_REV = "scenario-whatif/1"


def _guard(graph, scope: WhatIfScope) -> None:
    """SoC-agnostic: any project whose Timing Budget evaluates can run What-if (see whatif_targets capability)."""
    if graph.scenario.project_ref != scope.project_ref:
        raise UnprocessableError("What-if project does not own the selected scenario")


def _graph(db: Session, scope: WhatIfScope):
    try:
        graph = load_canonical_graph(db, scope.scenario_id, scope.variant_id)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    _guard(graph, scope)
    return graph


def targets(db: Session, scope: WhatIfScope) -> dict:
    graph = _graph(db, scope)
    try:
        out = whatif_targets(graph)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return {**scope.model_dump(), "baseline_hash": baseline_fingerprint(graph), **out,
            "soc_ref": out["capability"]["soc_ref"]}


def _baseline_clocks(db: Session, scope: WhatIfScope) -> dict[str, float]:
    """Set clock per IP in the baseline timing budget (same inputs as preview's baseline case)."""
    req = TimingBudgetRequest(scenario_id=scope.scenario_id, variant_id=scope.variant_id)
    shim = _shim(req, req.variant_id)
    _apply_config_profile(db, shim)
    graph, tables, ref = _load(db, shim, True)
    _guard(graph, scope)
    options = apply_throughput(req.options, scenario_policy(db, scope.scenario_id))
    report = _case(graph, shim.config, options, tables, ref)["report"]
    return {row["node"]: float(row["set_clock_mhz"]) for row in report["ips"] if row.get("set_clock_mhz")}


def _resolve_relative_clocks(db: Session, scope: WhatIfScope, out: dict) -> None:
    """Relative IP clocks ("20% 낮추면") -> MHz against the baseline set clock, in changes and in choices."""
    pending = [c for c in out["changes"] if "scale" in c] + [
        ch["change"] for cl in out["clarifications"] for ch in cl["choices"] if ch.get("change") and "scale" in ch["change"]]
    if not pending:
        return
    try:
        clocks = _baseline_clocks(db, scope)
    except (LookupError, ValueError) as exc:
        clocks, reason = {}, str(exc)
    else:
        reason = "기준 clock 없음"
    noted: set[str] = set()
    for change in pending:
        base = clocks.get(change["node_id"])
        scale = change.pop("scale")
        if base is None:
            change["unresolved"] = f"{change['node_id']} 기준 clock을 구하지 못했습니다 ({reason})"
            continue
        change["value"] = max(1.0, round(base * scale, 1))
        if change in out["changes"] and change["node_id"] not in noted:
            noted.add(change["node_id"])
            out["notes"].append(f"{change['node_id']} 기준 적용 clock {base:g} MHz × {scale:g} = {change['value']:g} MHz (수동 하한)")
    bad = [c for c in out["changes"] if c.get("unresolved")]
    if bad:
        for change in bad:
            out["ignored"].append({"text": change.pop("unresolved"), "reason": "상대 clock을 MHz로 바꾸지 못했습니다",
                                   "hint": "MHz 값으로 직접 지정"})
        out["changes"] = [c for c in out["changes"] if "value" in c or c["target"] != "node_clock_mhz"]
        if not out["changes"] and not out["clarifications"]:
            out["status"] = "unsupported"
        elif out["status"] == "ready":
            out["status"] = "partial"
    for cl in out["clarifications"]:
        cl["choices"] = [ch for ch in cl["choices"] if not (ch.get("change") or {}).get("unresolved")]
        for ch in cl["choices"]:
            change = ch.get("change") or {}
            if change.get("target") == "node_clock_mhz" and "value" in change and "MHz" not in ch["label"]:
                ch["label"] = f"{ch['label']} ({change['value']:g} MHz)"


def plan(db: Session, request: WhatIfPlanRequest) -> dict:
    scope = WhatIfScope(**request.model_dump(exclude={"query"}))
    available = targets(db, scope)
    out = plan_query(request.query, available)
    _resolve_relative_clocks(db, scope, out)
    return {**out, "baseline_hash": available["baseline_hash"], "scope": request.model_dump(exclude={"query"})}


def _case(graph, config, options, tables, ref):
    inputs = build_simulation_inputs(graph, config)
    _enforce_input_limits(inputs)
    report = analyze_timing_budget(graph, options, config=config, dvfs_tables=tables)
    report["dvfs"]["table_ref"] = ref
    missing = sorted({w.node_id for w in inputs.workloads
                      if w.sim_params.ppc <= 0 or w.sim_params.unit_power_mw_mp <= 0}
                     | {str(n["id"]) for n in graph.pipeline_nodes
                        if n.get("ip_ref") and n["ip_ref"] not in graph.ip_catalog})
    excluded = sorted({str(d.get("device_type") or "external_device") for d in inputs.external_devices})
    excluded.append("unmodeled SoC/display/device baseline and MIF DVFS")
    p = report["power"]
    coverage = {"complete": not missing and not excluded, "scope": "modeled CPU + IP + memory",
                "missing_components": missing, "excluded_components": excluded, "cpu_model": "flat",
                "assumptions": ["Per-frame SW runtime remains the baseline assumption; no measured extrapolation",
                                "Existing stream bitrate stays fixed", "Sensor mode and input dimensions stay fixed",
                                "FPS changes are hypothetical cadence; selected sensor mode support is not validated",
                                "Model calculation does not validate IQ or wiring compatibility"]}
    metrics = {"modeled_power_mw": p["total_mw"], "total_power_mw": p["total_mw"] if coverage["complete"] else None,
               "cpu_power_mw": p["cpu_mw"], "ip_power_mw": p["hw_mw"], "memory_power_mw": p["bw_mw"],
               "bw_mbs": report["bw"]["total_mbs"], "fps": report["fps"], "period_ms": report["period_ms"],
               "feasible": report["verdict"]["status"] != "fail"}
    return {"report": report, "metrics": metrics, "coverage": coverage}


def preview(db: Session, request: WhatIfPreviewRequest) -> dict:
    req = TimingBudgetRequest(scenario_id=request.scenario_id, variant_id=request.variant_id,
                              config=request.config.model_copy(deep=True), options=request.options.model_copy(deep=True))
    shim = _shim(req, req.variant_id)
    try:
        _apply_config_profile(db, shim)
        # An active basis can fill restricted inputs after the original request was validated.
        WhatIfPreviewRequest.model_validate(
            {**request.model_dump(), "config": shim.config.model_dump()})
        graph, tables, ref = _load(db, shim, True)
        _guard(graph, request)
        baseline_hash = baseline_fingerprint(graph)
        if baseline_hash != request.expected_baseline_hash:
            raise ConflictError("What-if baseline changed; interpret and preview the condition again")
        options = apply_throughput(req.options, scenario_policy(db, request.scenario_id))
        candidate, config, changes = apply_whatif_changes(graph, request.changes, shim.config)
        before = _case(graph, shim.config, options, tables, ref)
        after = _case(candidate, config, options, tables, ref)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    scope = request.model_dump(include={"project_ref", "scenario_id", "variant_id"})
    normalized = {"scope": scope, "changes": changes, "config": config.model_dump(mode="json"),
                  "options": options.model_dump(mode="json")}
    hash_payload = {"baseline": baseline_hash, "condition": normalized, "engine": ENGINE_REV,
                    "tables": {k: t.model_dump(mode="json") for k, t in tables.items()},
                    "baseline_config": shim.config.model_dump(mode="json"),
                    "baseline_inputs": build_simulation_inputs(graph, shim.config).model_dump(mode="json"),
                    "candidate_inputs": build_simulation_inputs(candidate, config).model_dump(mode="json"),
                    "resolved_candidate": baseline_fingerprint(candidate)}
    condition_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    metrics_delta = {key: round(value - before["metrics"][key], 4)
                     for key, value in after["metrics"].items()
                     if isinstance(value, (int, float)) and not isinstance(value, bool)
                     and isinstance(before["metrics"][key], (int, float))}
    baseline_ips = {row["node"]: row for row in before["report"]["ips"]}
    ips = []
    for row in after["report"]["ips"]:
        old = baseline_ips.get(row["node"])
        if old is None:
            continue
        reason = row.get("set_reason") or "calculated"
        leader = row.get("domain_leader")
        ips.append({"node": row["node"], **{k: round(row[k] - old[k], 4) for k in
                    ("required_clock_mhz", "set_clock_mhz", "power_mw")},
                    "explanation": f"set clock: {reason}" + (f" ({leader} shared domain)" if leader else "")})
    warnings = sorted(set(before["report"]["warnings"] + after["report"]["warnings"] + [
        "Calculated model subtotal excludes missing/unmodeled device power; it is not measured whole-device power.",
        "Condition changes keep assumed SW runtime and stream bitrate fixed; review those assumptions before adoption."]))
    return {"persisted": False, "baseline_hash": baseline_hash, "condition_hash": condition_hash,
            "normalized_condition": normalized, "baseline": before, "candidate": after,
            "delta": {"metrics": metrics_delta, "ips": ips}, "warnings": warnings,
            "model_lineage": {"engine": "timing-budget", "engine_rev": ENGINE_REV,
                "power_model": config.power_model, "power_params_ref": config.power_params_ref,
                "dvfs_table_ref": ref, "cpu_model": "flat", "baseline_fingerprint": baseline_hash}}


def _record(row, *, detail=False):
    keys = ("id", "project_ref", "title", "purpose", "description", "assumptions", "conclusion", "query",
            "visibility", "created_by", "baseline_hash", "condition_hash")
    out = {key: getattr(row, key) for key in keys}
    out.update(scenario_id=row.scenario_ref, variant_id=row.variant_ref,
               created_at=row.created_at.isoformat() if row.created_at else None)
    if detail:
        out.update(preview_request=row.preview_request, normalized_condition=row.normalized_condition, result=row.result)
    else:
        out["metrics"] = (row.result or {}).get("candidate", {}).get("metrics", {})
    return out


def save_experiment(db: Session, request: WhatIfExperimentRequest, subject: str) -> dict:
    result = preview(db, request.preview_request)
    if result["condition_hash"] != request.expected_condition_hash:
        raise ConflictError("What-if calculation inputs changed; preview again before saving")
    scope = request.preview_request
    row = WhatIfExperiment(id=f"whatif-{uuid4().hex}", project_ref=scope.project_ref,
                          scenario_ref=scope.scenario_id, variant_ref=scope.variant_id,
                          title=request.title.strip(), purpose=request.purpose, description=request.description,
                          assumptions=request.assumptions, conclusion=request.conclusion, query=request.query,
                          visibility=request.visibility, created_by=subject,
                          baseline_hash=result["baseline_hash"], condition_hash=result["condition_hash"],
                          preview_request=scope.model_dump(mode="json"),
                          normalized_condition=result["normalized_condition"], result=result)
    if not row.title:
        raise UnprocessableError("experiment title cannot be blank")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _record(row, detail=True)


def _list_scope(db: Session, project_ref: str, scenario_id: str | None = None):
    project: Any = db.get(Project, project_ref)
    if project is None:
        raise NotFoundError("What-if project not found")
    if scenario_id:
        scenario = db.get(Scenario, scenario_id)
        if scenario is None or scenario.project_ref != project_ref:
            raise NotFoundError("What-if scenario not found in selected project")


def list_experiments(db: Session, subject: str, project_ref: str, *, scenario_id: str | None = None,
                     variant_id: str | None = None, limit=30, offset=0):
    _list_scope(db, project_ref, scenario_id)
    query = db.query(WhatIfExperiment).filter(WhatIfExperiment.project_ref == project_ref,
                or_(WhatIfExperiment.visibility == "shared", WhatIfExperiment.created_by == subject))
    if scenario_id:
        query = query.filter(WhatIfExperiment.scenario_ref == scenario_id)
    if variant_id:
        query = query.filter(WhatIfExperiment.variant_ref == variant_id)
    total = query.count()
    rows = query.order_by(WhatIfExperiment.created_at.desc(), WhatIfExperiment.id).offset(offset).limit(limit).all()
    return {"items": [_record(row) for row in rows], "total": total, "limit": limit,
            "offset": offset, "has_next": offset + limit < total}


def get_experiment(db: Session, experiment_id: str, subject: str):
    row: Any = db.query(WhatIfExperiment).filter(WhatIfExperiment.id == experiment_id,
              or_(WhatIfExperiment.visibility == "shared", WhatIfExperiment.created_by == subject)).one_or_none()
    if row is None:
        raise NotFoundError("What-if experiment not found")
    _list_scope(db, row.project_ref, row.scenario_ref)
    return _record(row, detail=True)
