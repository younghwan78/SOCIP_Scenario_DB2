"""Stage timing budget API service (read-only; never persists)."""

from __future__ import annotations

from typing import Any

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
from scenario_db.exceptions import ConflictError, NotFoundError, UnprocessableError
from scenario_db.models.evidence.common import ExecutionContext
from scenario_db.api.services.cpu import with_cpu_profile
from scenario_db.api.services.failures import variant_failure
from scenario_db.api.services.review_policy import apply_throughput, scenario_policy
from scenario_db.sim.adapter import build_simulation_inputs
from scenario_db.sim.service import (
    _apply_config_profile,
    _check_power_params_scope,
    _dvfs_tables_from_row,
    _enforce_input_limits,
    _graph_soc_ref,
    _resolve_dvfs_tables,
    _request_hash,
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
    _check_power_params_scope(shim.config, graph)
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


def _condition_hash(graph, options, shim, tables) -> str:
    """Fingerprint resolved inputs, tables and timing choices; display-only options do not change the condition."""
    import hashlib
    import json

    payload = {"simulation": _request_hash(build_simulation_inputs(graph, shim.config), shim, dvfs_tables=tables),
               "options": options.model_dump(mode="json", exclude={"include_whatif", "whatif_scales", "timeline_frames"})}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _check_condition(request, condition_hash: str) -> None:
    if request.expected_condition_hash is not None and request.expected_condition_hash != condition_hash:
        raise ConflictError("Timing Budget inputs changed; recalculate before saving or registering")


def _validate_measured_cpu(request, options, config) -> None:
    """An explicit measured CPU input must be usable rather than silently reverting to the flat model."""
    if getattr(request, "measured", None) is None or not request.measured.cpu:
        return
    from scenario_db.sim.power_params import effective_power_params

    params = effective_power_params(config)
    if options.cpu_profile is None or params is None or not params.cpu.clusters:
        raise UnprocessableError("Measured CPU input requires a per-frame CPU profile and power_model_params with cpu.clusters")


def analyze_timing_budget_request(
    db: Session, request: TimingBudgetRequest
) -> TimingBudgetResponse:
    original = request
    request = apply_measured(db, request)
    shim = _shim(request, request.variant_id)
    profile = _apply_config_profile(db, shim)
    try:
        graph, tables, ref = _load(db, shim, request.use_default_dvfs)
        options = with_cpu_profile(db, apply_throughput(request.options, scenario_policy(db, request.scenario_id)),
                                   request.scenario_id, request.variant_id)
        _validate_measured_cpu(request, options, shim.config)
        report = analyze_timing_budget(
            graph, options, config=shim.config, dvfs_tables=tables
        )
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    report["dvfs"]["table_ref"] = ref
    report["measured_compare"] = measured_compare(db, original, report)
    report["condition"] = {"task_runtime": {k: v.model_dump() for k, v in options.task_runtime.items()},
                           "measured_clock_ref": shim.config.measured_clock_ref, "clock_basis": shim.config.clock_basis,
                           "cpu_profile_ref": options.cpu_profile_ref if options.cpu_model == "profile" else None}
    report["condition_hash"] = _condition_hash(graph, options, shim, tables)
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
    options = apply_throughput(request.options, scenario_policy(db, request.scenario_id)).model_copy(update={"include_whatif": False})
    ids = list(dict.fromkeys(ids))
    if len(ids) > 200:
        raise UnprocessableError("fleet scope exceeds 200 variants; select a bounded subset")
    out, errors, ref, profile = [], [], None, None
    for variant_id in ids:
        shim = _shim(request, variant_id)
        profile = _apply_config_profile(db, shim)
        stage = "load"
        try:
            graph, tables, ref = _load(db, shim, request.use_default_dvfs)
            stage = "timing_budget"
            out.append(
                fleet_row(
                    analyze_timing_budget(graph, with_cpu_profile(db, options, request.scenario_id, variant_id),
                                          config=shim.config, dvfs_tables=tables)
                )
            )
        except Exception as exc:  # noqa: BLE001 - one variant must not abort the fleet
            errors.append(variant_failure(exc, variant_id=variant_id, stage=stage))
    return TimingBudgetFleetResponse(
        scenario_id=request.scenario_id,
        config_profile_ref=profile,
        dvfs_table_ref=ref,
        rows=out,
        errors=errors,
    )


def analyze_dvfs_whatif_request(db: Session, request: Any) -> dict[str, Any]:
    """DVFS level +/-k what-if for one variant (``sim.timing_budget.dvfs_level_whatif``)."""
    from scenario_db.sim.timing_budget import dvfs_level_whatif

    request = apply_measured(db, request)
    shim = _shim(request, request.variant_id)
    profile = _apply_config_profile(db, shim)
    try:
        graph, tables, ref = _load(db, shim, request.use_default_dvfs)
        options = with_cpu_profile(db, apply_throughput(request.options, scenario_policy(db, request.scenario_id)),
                                   request.scenario_id, request.variant_id)
        _validate_measured_cpu(request, options, shim.config)
        out = dvfs_level_whatif(graph, options, config=shim.config, dvfs_tables=tables,
                                shifts=tuple(sorted(set(request.shifts))), domains=request.domains, combos=request.combos)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return {"scenario_id": request.scenario_id, "variant_id": request.variant_id, "config_profile_ref": profile,
            "dvfs_table_ref": ref, **out}


def interval_distribution_request(db: Session, request: Any) -> dict[str, Any]:
    """③ box plot: output interval / latency spread under per-frame SW variance (read-only)."""
    from scenario_db.sim.timing_budget import interval_distribution

    request = apply_measured(db, request)
    shim = _shim(request, request.variant_id)
    _apply_config_profile(db, shim)
    try:
        graph, tables, _ref = _load(db, shim, request.use_default_dvfs)
        options = with_cpu_profile(db, apply_throughput(request.options, scenario_policy(db, request.scenario_id)),
                                   request.scenario_id, request.variant_id)
        _validate_measured_cpu(request, options, shim.config)
        out = interval_distribution(graph, options, config=shim.config, dvfs_tables=tables,
                                    trials=request.trials, frames=request.frames)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return {"scenario_id": request.scenario_id, "variant_id": request.variant_id, **out}


def register_condition(db: Session, request: Any, user: str | None = None) -> dict[str, Any]:
    """Register the Timing Budget condition as the current prediction.

    The condition becomes a single-case exploration run (one SW statistic x growth, no DVFS headroom, no compression /
    power options; DVFS overrides and the config profile travel in the run's input selection), so freshness, history
    and attribution work exactly like an exploration registration. Rule: ``manual:timing-budget``.
    """
    from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest, PromoteRequest
    from scenario_db.api.services.arch_exploration import promote, run_exploration
    from scenario_db.sim.arch_exploration import ArchExplorationSpec

    original = request
    request = apply_measured(db, request)
    shim = _shim(request, request.variant_id)
    _apply_config_profile(db, shim)
    try:
        graph, tables, _ref = _load(db, shim, request.use_default_dvfs)
        options = with_cpu_profile(db, apply_throughput(request.options, scenario_policy(db, request.scenario_id)),
                                   request.scenario_id, request.variant_id)
        _validate_measured_cpu(request, options, shim.config)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    _check_condition(request, _condition_hash(graph, options, shim, tables))
    o = request.options
    spec = ArchExplorationSpec.model_validate({
        "axes": {"statistics": [o.statistic], "runtime_scales": [o.runtime_scale], "eis": o.eis,
                 "dvfs_headroom_levels": 0, "compression": {"enabled": False}, "power_options": {"enabled": False}},
        "objective": {"statistic": o.statistic, "runtime_scale": o.runtime_scale},
        "timing": o.model_dump(exclude_unset=True, exclude={"include_whatif"}),
        "top_n": 1,
    })
    run_req = ArchExplorationRunRequest(
        title=f"Timing Budget · {request.variant_id}", scenario_type="timing-budget",
        scenario_ids=[request.scenario_id], variant_ids=[request.variant_id], include_derived=True, max_variants=1,
        config=request.config, config_profile_ref=request.config_profile_ref, dvfs_tables=request.dvfs_tables,
        dvfs_table_ref=request.dvfs_table_ref, soc_ref=request.soc_ref, dvfs_version=request.dvfs_version,
        use_default_dvfs=request.use_default_dvfs, spec=spec,
        timing_budget={"measured": original.measured.model_dump() if original.measured else None,
                       "task_runtime": {k: v.model_dump() for k, v in original.options.task_runtime.items()}},
    )
    run = run_exploration(db, run_req, user)
    if not run["variants"]:
        raise UnprocessableError("timing budget condition could not be evaluated")
    summary = run["variants"][0]
    rec = summary.get("recommended")
    if rec is None:
        raise UnprocessableError("이 조건은 spec 미달이라 등록할 수 없습니다: " + "; ".join(summary.get("spec_reasons") or ["no eligible case"]))
    out = promote(db, PromoteRequest(run_id=run["id"], scenario_id=request.scenario_id, variant_ids=[request.variant_id],
                                     case_key=rec["key"], reason=request.reason,
                                     expected_project_ref=request.expected_project_ref),
                  user, rule="manual:timing-budget")
    return out | {"total_mw": rec.get("total_mw")}


def save_condition_evidence(db: Session, request: Any, user: str | None = None) -> dict[str, Any]:
    """Keep the condition's budget run as simulation evidence (Pipeline trace, Compare, Calibration).

    The evidence id is derived from the whole condition, so saving the same condition twice (by anyone) converges on
    one row; ``existed`` tells the caller."""
    import hashlib
    import json

    from scenario_db.db.models.definition import Project, Scenario
    from scenario_db.db.repositories.evidence import get_evidence, upsert_simulation_evidence
    from scenario_db.sim.runner import build_simulation_evidence
    from scenario_db.sim.timing_budget import budget_simulation

    original = request
    request = apply_measured(db, request)
    shim = _shim(request, request.variant_id)
    profile = _apply_config_profile(db, shim)
    scenario = db.get(Scenario, request.scenario_id)
    if scenario is None:
        raise NotFoundError(f"scenario not found: {request.scenario_id}")
    ctx = request.execution_context
    if ctx is None:
        project = db.get(Project, scenario.project_ref) if scenario.project_ref else None
        sw = ((project.metadata_ or {}).get("default_sw_profile_ref") or (project.globals_ or {}).get("default_sw_profile_ref")) if project else None
        if not sw:
            raise UnprocessableError("execution_context.sw_baseline_ref is required (project has no default_sw_profile_ref)")
        ctx = ExecutionContext(silicon_rev="EVT1", sw_baseline_ref=sw, thermal="nominal", method="calculation")
    try:
        graph, tables, ref = _load(db, shim, request.use_default_dvfs)
        options = with_cpu_profile(db, apply_throughput(request.options, scenario_policy(db, request.scenario_id)),
                                   request.scenario_id, request.variant_id)
        _validate_measured_cpu(request, options, shim.config)
        condition_hash = _condition_hash(graph, options, shim, tables)
        _check_condition(request, condition_hash)
        result = budget_simulation(graph, options, config=shim.config, dvfs_tables=tables)
        report = analyze_timing_budget(graph, options.model_copy(update={"include_whatif": False}),
                                       config=shim.config, dvfs_tables=tables)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    condition = {"condition_hash": condition_hash, "options": options.model_dump(mode="json"), "config": shim.config.model_dump(mode="json", exclude_none=True),
                 "dvfs_table_ref": ref, "context": ctx.model_dump(mode="json", exclude_none=True)}
    digest = "tb" + hashlib.sha256(json.dumps(condition, sort_keys=True, default=str).encode()).hexdigest()[:16]
    ctx = ctx.model_copy(update={"dvfs_table_ref": ref}) if ref and ctx.dvfs_table_ref is None else ctx
    evidence = build_simulation_evidence(result, execution_context=ctx, project_ref=scenario.project_ref,
                                         params_hash=digest, config_profile_ref=profile)
    power = report["power"]
    kpi = dict(evidence.kpi or {}) | {"total_power_mw": power["total_mw"], "cpu_power_mw": power["cpu_mw"],
                                    "core_power_mw": power["hw_mw"], "bw_power_mw": power["bw_mw"],
                                    "total_power_ma": power["total_mw"] / shim.config.vbat,
                                    "total_bw_mbs": report["bw"]["total_mbs"]}
    pb = dict(evidence.power_breakdown or {})
    for key, mw in (("ip", power["hw_mw"]), ("memory", power["bw_mw"])):
        pb[key] = {**(pb.get(key) if isinstance(pb.get(key), dict) else {}), "total_mw": mw}
    pb["cpu"] = {"total_mw": power["cpu_mw"], "by_task": power["cpu_by_task"],
                 "model": power.get("cpu_profile") or power["cpu_model"]}
    pb.update(total_mw=power["total_mw"], source="timing_budget")
    evidence = evidence.model_copy(update={"kpi": kpi, "power_breakdown": pb})
    sources = [*evidence.derived_from, options.cpu_profile_ref if options.cpu_model == "profile" else None,
               shim.config.measured_clock_ref,
               original.measured.measurement_ref if original.measured and original.measured.sw else None]
    evidence = evidence.model_copy(update={"derived_from": list(dict.fromkeys(s for s in sources if s)),
                                          "run": evidence.run.model_copy(update={
        "tool": "scenariodb-timing-budget", "timing_budget": {
            "condition_hash": condition_hash, "options": options.model_dump(mode="json", exclude={"cpu_profile"}),
            "measured": original.measured.model_dump() if original.measured else None,
            "dvfs_overrides": shim.config.dvfs_overrides, "dvfs_table_ref": ref},
        **({"writer": user} if user else {})})})
    existed = get_evidence(db, evidence.id) is not None
    if not existed:
        upsert_simulation_evidence(db, evidence)
        db.commit()
    return {"evidence_id": evidence.id, "existed": existed, "params_hash": digest,
            "total_mw": evidence.kpi.get("total_power_mw") if isinstance(evidence.kpi, dict) else None}


# ------------------------------------------------------------------- S4: measurement as input / reference
def _measurement(db: Session, request: Any):
    from scenario_db.db.repositories.evidence import get_evidence

    ref = request.measured.measurement_ref
    row = get_evidence(db, ref)
    if row is None or row.kind != "evidence.measurement":
        raise NotFoundError(f"measurement evidence not found: {ref}")
    if (row.scenario_ref, row.variant_ref) != (request.scenario_id, request.variant_id):
        raise UnprocessableError(f"measurement evidence {ref} belongs to {row.scenario_ref}/{row.variant_ref}")
    return row


def _sw_stats(row) -> dict[str, dict[str, float]]:
    """Measured SW task runtime per task: min / mean / max (p50 / p95 stand in when min / max are missing)."""
    out: dict[str, dict[str, float]] = {}
    for t in row.sw_task_timing or []:
        if not isinstance(t, dict) or not t.get("task") or t.get("mean_ms") is None:
            continue
        # per-invocation statistics x invocations per frame = time per frame
        k = float(t["count_per_frame"]) if t.get("sample_unit", "invocation") == "invocation" and t.get("count_per_frame") is not None else 1.0
        mean = float(t["mean_ms"])
        lo = float(t.get("min_ms") if t.get("min_ms") is not None else t.get("p50_ms") if t.get("p50_ms") is not None else mean)
        hi = float(t.get("max_ms") if t.get("max_ms") is not None else t.get("p95_ms") if t.get("p95_ms") is not None else mean)
        out[str(t["task"])] = {"min_ms": round(min(lo, mean) * k, 4), "mean_ms": round(mean * k, 4), "max_ms": round(max(hi, mean) * k, 4)}
    return out


def _clock_count(row) -> int:
    from scenario_db.sim.measured_clock import measured_clocks_from_observations

    try:
        return len(measured_clocks_from_observations(row.metric_observations or [], stat="weighted_mean", evidence_ref=str(row.id)))
    except Exception:  # noqa: BLE001 - unusable observations = no clock input
        return 0


def apply_measured(db: Session, request: Any) -> Any:
    """Turn ``request.measured`` into plain options / config fields, so the condition (and a registration or saved
    evidence made from it) carries the measured inputs explicitly: SW -> ``options.task_runtime``, clock ->
    ``config.measured_clock_ref`` + ``clock_basis="measured"``, CPU -> ``options.cpu_model="profile"`` + ``cpu_profile_ref``."""
    m = getattr(request, "measured", None)
    if m is None:
        return request
    row = _measurement(db, request)
    if not (m.sw or m.clock or m.cpu):
        return request
    options, config = request.options, request.config
    if m.sw:
        stats = _sw_stats(row)
        if not stats:
            raise UnprocessableError(f"measurement {row.id} has no SW task timing")
        from scenario_db.sim.timing_budget import TimingStat

        options = options.model_copy(update={"task_runtime": {**{k: TimingStat(**v) for k, v in stats.items()}, **options.task_runtime}})
    if m.cpu:
        options = options.model_copy(update={"cpu_model": "profile", "cpu_profile_ref": str(row.id), "cpu_profile": None})
    if m.clock:
        if not _clock_count(row):
            raise UnprocessableError(f"measurement {row.id} has no usable clock.ip observations")
        config = config.model_copy(update={"measured_clock_ref": str(row.id), "measured_clocks": None, "clock_basis": "measured"})
    return request.model_copy(update={"options": options, "config": config})


def measured_compare(db: Session, request: Any, report: dict[str, Any]) -> dict[str, Any] | None:
    """Predicted (this condition) vs the selected measurement: total and CPU / IP / BW / other rails."""
    m = getattr(request, "measured", None)
    if m is None:
        return None
    from scenario_db.api.services.calibration import measurement_detail
    from scenario_db.comparison.calibration import compare_split, pct

    d = measurement_detail(db, m.measurement_ref)
    if (d["scenario_id"], d["variant_id"]) != (request.scenario_id, request.variant_id):
        raise UnprocessableError("measurement belongs to another variant")
    p = report["power"]
    pred = {"cpu": p["cpu_mw"], "ip": p["hw_mw"], "bw": p["bw_mw"]}
    meas_total = (d.get("total") or {}).get("mean")
    return {
        "measurement_ref": d["id"], "measured_at": d.get("measured_at"), "synthetic": d.get("synthetic"), "origin": d.get("origin"),
        "context": d.get("context"), "inputs": {"sw": m.sw, "clock": m.clock, "cpu": m.cpu},
        "total": {"prediction_mw": p["total_mw"], "measurement_mw": meas_total, "delta_pct": pct(p["total_mw"], meas_total),
                  "delta_mw": None if meas_total is None else round(p["total_mw"] - meas_total, 3)},
        "rows": compare_split(pred, d["measured"]["categories"]),
        "unexplained_mw": d.get("unexplained_mw"), "fps": d.get("fps"), "frame_latency": d.get("frame_latency"),
        "sw_tasks": d.get("sw_tasks") or [],
    }


def measured_inputs(db: Session, scenario_id: str, variant_id: str) -> list[dict[str, Any]]:
    """Measurements of a variant usable as inputs: which parts each one can supply (SW / clock / CPU)."""
    from scenario_db.api.services.calibration import _total, data_origin, is_synthetic
    from scenario_db.api.services.cpu import resolve_cpu_profile
    from scenario_db.db.models.evidence import Evidence

    rows = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref == scenario_id,
                                      Evidence.variant_ref == variant_id)
            .order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all())
    out = []
    for r in rows:
        try:
            cpu = resolve_cpu_profile(db, scenario_id, variant_id, str(r.id))[0] is not None
        except Exception:  # noqa: BLE001 - no usable CPU profile in this measurement
            cpu = False
        out.append({"id": r.id, "measured_at": r.measured_at.isoformat() if r.measured_at else None,
                    "synthetic": is_synthetic(r.provenance), "origin": data_origin(r.provenance),
                    "total_mw": _total(r.kpi).get("mean"), "sw_tasks": sorted(_sw_stats(r)), "clock_ips": _clock_count(r), "cpu": cpu,
                    "context": {k: (r.execution_context or {}).get(k) for k in ("silicon_rev", "sw_baseline_ref", "thermal")}})
    out.sort(key=lambda x: (x["synthetic"], x["measured_at"] is None))
    return out
