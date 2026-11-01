from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, replace
from threading import Condition, RLock
from typing import Any, Literal

from sqlalchemy.orm import Session

from scenario_db.api.schemas.cpu import CpuRebalanceRequest, CpuSweepRequest, CpuWhatIfRequest, CpuWhatIfResponse
from scenario_db.api.services.compute_session import release_read_connection
from scenario_db.db.models.capability import PowerModelParams as PowerModelParamsRow
from scenario_db.db.repositories.evidence import get_evidence
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_profile import cpu_profile_from_evidence
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance
from scenario_db.sim.cpu_sched import StageOrder, SweepSpec, cpu_sweep, longest_path
from scenario_db.sim.cpu_whatif import WhatIfSpec, cpu_whatif
from scenario_db.sim.power_params import power_params_from_row


def _model(db: Session, ref: str) -> CpuPowerModel:
    params_id, _, version = ref.partition("@")
    row = db.get(PowerModelParamsRow, params_id)
    if row is None:
        raise NotFoundError(f"power_model_params not found: {ref}")
    if version and (not version.isdigit() or int(version) != row.version):
        raise UnprocessableError(f"power_model_params '{params_id}' is at version {row.version}, requested '{version}'")
    params = power_params_from_row(row)
    if not params.cpu.clusters:
        raise UnprocessableError(f"power_model_params '{ref}' has no cpu topology (cpu.clusters)")
    return CpuPowerModel.from_params(params)


def _profile(db: Session, request: CpuWhatIfRequest | CpuSweepRequest) -> Any:
    profile = request.cpu_profile
    if profile is None:
        if not request.cpu_profile_ref:
            raise UnprocessableError("give cpu_profile_ref or cpu_profile")
        row = get_evidence(db, request.cpu_profile_ref)
        if row is None or row.kind != "evidence.measurement":
            raise NotFoundError(f"measurement evidence not found: {request.cpu_profile_ref}")
        profile = cpu_profile_from_evidence(row, evidence_ref=request.cpu_profile_ref)
        if profile is None:
            raise UnprocessableError(f"measurement evidence {request.cpu_profile_ref} has no per-frame CPU profile")
    return profile


def _sweep_fields(request: CpuSweepRequest) -> dict[str, Any]:
    return dict(
        growth=request.growth, default_growth=request.default_growth, budgets_ms=request.budgets_ms,
        threads=request.threads, sweep_clusters=request.sweep_clusters, knobs=tuple(request.knobs),
        uclamp_max_levels=tuple(request.uclamp_max_levels), uclamp_min_levels=tuple(request.uclamp_min_levels),
        task_policy={t: p.model_dump() for t, p in request.task_policy.items()}, reference=request.reference,
        power_gating_eff=request.power_gating_eff, cpu_bw_scale=request.cpu_bw_scale,
        freq_margin=request.freq_margin, fits_margin=request.fits_margin, util_model=request.util_model,
        pelt_halflife_ms=request.pelt_halflife_ms, deadline_boost=request.deadline_boost,
        energy_includes_static=request.energy_includes_static, max_cases=request.max_cases, top=request.top,
        dsu_mode=request.dsu_mode, dsu_vote=request.dsu_vote, dsu_fixed_mhz=request.dsu_fixed_mhz,
    )


def run_cpu_sweep(db: Session, request: CpuSweepRequest) -> CpuWhatIfResponse:
    data = _rebalance_data(db, request)
    # the same Timing Budget coupling as the rebalance: stage budgets (stage_slack) and the stage SW order
    coupling, enforce = _timing_coupling(db, request, data)
    spec = SweepSpec(**_sweep_fields(request), stretch_budgets=dict(coupling["stretch"]) if coupling and enforce else {},
                     serial_stages=coupling_stages(coupling))
    release_read_connection(db)
    try:
        result = cpu_sweep(data.profile, target=data.target, base=data.base, fps=request.fps, spec=spec)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    if coupling:
        # the coupling's SW times belong to the measured placement: impacts scale from it, also with reference=eas
        measured = result["measured_placement"]
        coupling["enforced"] = enforce
        matched = sorted(t for t in coupling["stretch"] if t in (measured.get("task_ms") or {}))
        coupling["matched_tasks"], coupling["unmatched_tasks"] = matched, sorted(set(coupling["stretch"]) - set(matched))
        best = (result.get("cases") or [None])[0]
        coupling["impact"] = {"reference": timing_impact(coupling, measured, result["reference"]),
                              "best": timing_impact(coupling, measured, best) if best else None}
        result["timing_coupling"] = coupling
    result["timing_mode"] = request.timing_coupling
    return CpuWhatIfResponse(profile_ref=data.profile.evidence_ref, power_params_ref=request.power_params_ref, result=result)


def timing_stretch(db: Session, scenario_id: str, variant_id: str, *, statistic: Literal["min", "mean", "max"] = "max",
                   runtime_scale: float = 1.0, growth: dict[str, float] | None = None) -> dict[str, Any]:
    """Per-task slow-down allowed by the variant's Timing Budget (stage SW slack), plus the stage table.

    room = P - HW - overhead of the stage; stretch = room / SW (>= 1: a stage already over the 25 %-style
    budget allows no slow-down at all). Each SW item of the stage gets the stage's stretch, so the stage SW
    total stays within its room when every task slows down by the same factor (conservative split).
    """
    from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
    from scenario_db.api.services.timing_budget import analyze_timing_budget_request
    from scenario_db.sim.timing_budget import SwTaskAdjustment, TimingBudgetOptions

    opts = TimingBudgetOptions(statistic=statistic, runtime_scale=runtime_scale, include_whatif=False)
    if growth:
        # CPU-only tasks ((other), HAL threads) have no Timing Budget item: their growth only scales CPU demand
        sw_tasks = _sw_tasks(db, scenario_id, variant_id)
        growth = {t: g for t, g in growth.items() if t in sw_tasks}
    if growth:
        if runtime_scale <= 0:
            raise UnprocessableError("task-specific growth needs positive default_growth for timing coupling")
        opts.task_adjustments = {t: SwTaskAdjustment(scale=g / runtime_scale) for t, g in growth.items()}
    rep = analyze_timing_budget_request(db, TimingBudgetRequest(scenario_id=scenario_id, variant_id=variant_id,
                                                                options=opts)).report
    period = float(rep["period_ms"])
    stages: list[dict[str, Any]] = []
    stretch: dict[str, float] = {}
    for st in rep["stages"]:
        items = [i for i in st.get("sw_items") or [] if i.get("kind", "sw") == "sw"]
        sw = float(st.get("sw_ms") or 0.0)
        if not items or sw <= 0:
            continue
        room = period - float(st.get("hw_ms") or 0.0) - float(st.get("overhead_ms") or 0.0)
        factor = max(1.0, room / sw)
        for i in items:
            stretch[i["task"]] = min(stretch.get(i["task"], math.inf), factor)
        stages.append({"stage": st["id"], "sw_ms": round(sw, 3), "hw_ms": round(float(st.get("hw_ms") or 0.0), 3),
                       "overhead_ms": round(float(st.get("overhead_ms") or 0.0), 3), "room_ms": round(room, 3),
                       "slack_ms": round(room - sw, 3), "stretch": round(factor, 3),
                       "tasks": [{"task": i["task"], "ms": float(i.get("runtime_ms") or 0.0),
                                  "latency_ms": float(i.get("latency_ms") or 0.0)} for i in items],
                       # SW pairs the pipeline orders within one frame (RT chain), from the variant's task graph
                       "order": [list(pair) for pair in st.get("sw_order") or []]})
    return _mark_serial({"mode": "stage_slack", "scenario_id": scenario_id, "variant_id": variant_id, "statistic": statistic,
                         "runtime_scale": runtime_scale, "period_ms": period, "stages": stages,
                         "stretch": {k: round(v, 4) for k, v in stretch.items()}})


def _sw_tasks(db: Session, scenario_id: str, variant_id: str) -> set[str]:
    """SW task ids of the variant's timeline (what TimingBudgetOptions.task_adjustments accepts)."""
    from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
    from scenario_db.api.services.analysis_inputs import resolve_analysis_selection
    from scenario_db.sim.timeline_adapter import timeline_tasks

    graph = resolve_analysis_selection(db, TimingBudgetRequest(scenario_id=scenario_id, variant_id=variant_id)).load(db).graph
    return {str(t["id"]) for t in timeline_tasks(graph) if t.get("task_type") == "sw"}


def _mark_serial(coupling: dict[str, Any]) -> dict[str, Any]:
    """``serial`` per stage and ``serial_pairs``: a stage's SW order holds within one frame only while the stage
    chain (SW + HW + overhead) fits one period; a longer chain overlaps the next frame's members, so they count
    as concurrent (conservative)."""
    pairs: list[list[str]] = []
    for st in coupling["stages"]:
        st["serial"] = bool(st.get("order")) and st["sw_ms"] + st["hw_ms"] + st["overhead_ms"] <= coupling["period_ms"] + 1e-6
        if st["serial"]:
            pairs += st["order"]
    coupling["serial_pairs"] = pairs
    return coupling


def coupling_stages(coupling: dict[str, Any] | None) -> tuple[StageOrder, ...]:
    """``SweepSpec.serial_stages`` of a coupling (also when it is only reported: ordering is not a budget). Every
    stage with an order goes in; whether it holds is decided per candidate from its task times (StageOrder.holds)."""
    if not coupling:
        return ()
    return tuple(StageOrder(stage=str(st["stage"]), pairs=tuple((str(a), str(b)) for a, b in st["order"]),
                            sw_ms=float(st["sw_ms"]), fixed_ms=float(st["hw_ms"]) + float(st["overhead_ms"]),
                            items=tuple((str(t["task"]), float(t["ms"])) for t in st["tasks"]),
                            period_ms=float(coupling["period_ms"]),
                            latency_ms=tuple((str(t["task"]), float(t.get("latency_ms") or 0.0)) for t in st["tasks"]))
                 for st in coupling["stages"] if st.get("order"))


def timing_impact(coupling: dict[str, Any], reference: dict[str, Any], case: dict[str, Any]) -> list[dict[str, Any]]:
    """Stage SW after a placement: each Timing Budget SW item scales with its CPU task time (case / reference)."""
    out = []
    ref_ms, new_ms = reference.get("task_ms") or {}, case.get("task_ms") or {}
    for st in coupling["stages"]:
        scaled = {it["task"]: it["ms"] * (new_ms[it["task"]] / ref_ms[it["task"]])
                  if ref_ms.get(it["task"]) and new_ms.get(it["task"]) else it["ms"] for it in st["tasks"]}
        if "order" in st:     # the stage SW is its critical path: parallel branches do not add up
            pairs = [(a, b) for a, b in st["order"]]
            lat = {it["task"]: float(it.get("latency_ms") or 0.0) for it in st["tasks"]}
            add = longest_path(scaled, pairs, lat) - longest_path({it["task"]: it["ms"] for it in st["tasks"]}, pairs, lat)
        else:                 # an older coupling without the order: every item in sequence
            add = sum(scaled[it["task"]] - it["ms"] for it in st["tasks"])
        sw = st["sw_ms"] + add
        period = coupling["period_ms"]
        chain0 = st["sw_ms"] + st["hw_ms"] + st["overhead_ms"]
        chain = chain0 + add
        # pipelined: fps holds while each task fits a frame; a longer SW+HW chain only adds buffered frames (latency)
        extra = max(0, math.ceil(chain / period - 1e-9) - math.ceil(chain0 / period - 1e-9)) if period > 0 else 0
        out.append({"stage": st["stage"], "sw_ms": round(sw, 3), "delta_sw_ms": round(add, 3),
                    "slack_ms": round(st["room_ms"] - sw, 3), "chain_ms": round(chain, 3),
                    "extra_latency_frames": extra, "ok": st["room_ms"] - sw >= -1e-6 or add <= 1e-6})
    return out


def latency_trade(coupling: dict[str, Any], enforced: dict[str, Any], free_best: dict[str, Any] | None) -> dict[str, Any] | None:
    """What dropping the stage-SW budgets buys: the period-only best vs the latency-keeping best, and its latency cost."""
    if not free_best:
        return None
    keep = enforced.get("best") or enforced["reference"]
    rows = timing_impact(coupling, enforced["reference"], free_best)
    return {"best_total_mw": free_best["total_mw"], "moved": free_best.get("moved") or [],
            "delta_mw": round(free_best["total_mw"] - keep["total_mw"], 2),
            "delta_vs_reference_mw": round(free_best["total_mw"] - enforced["reference"]["total_mw"], 2),
            "extra_latency_frames": max((r["extra_latency_frames"] for r in rows), default=0),
            "min_slack_ms": min((r["slack_ms"] for r in rows), default=None), "impact": rows}


def scale_coupling(coupling: dict[str, Any], runtime_scale: float) -> dict[str, Any]:
    """A ``timing_stretch`` result at another uniform SW growth: stage room is fixed, SW scales linearly."""
    k = runtime_scale / float(coupling["runtime_scale"])
    stages: list[dict[str, Any]] = []
    stretch: dict[str, float] = {}
    for st in coupling["stages"]:
        sw = st["sw_ms"] * k
        factor = max(1.0, st["room_ms"] / sw) if sw > 0 else 1.0
        tasks = [t | {"ms": t["ms"] * k} for t in st["tasks"]]   # runtime scales, latency stays
        for t in tasks:
            stretch[t["task"]] = min(stretch.get(t["task"], math.inf), factor)
        stages.append(st | {"sw_ms": round(sw, 3), "slack_ms": round(st["room_ms"] - sw, 3), "stretch": round(factor, 3), "tasks": tasks})
    return _mark_serial(coupling | {"runtime_scale": runtime_scale, "stages": stages, "stretch": {t: round(v, 4) for t, v in stretch.items()}})


@dataclass(frozen=True)
class _RebalanceData:
    profile: Any
    target: CpuPowerModel
    base: CpuPowerModel | None
    scope: tuple[str, str] | None


def _rebalance_data(db: Session, request: CpuSweepRequest) -> _RebalanceData:
    """Resolve invariant CPU inputs once; no ORM objects escape this preparation."""
    profile = _profile(db, request)
    target = _model(db, request.power_params_ref)
    base = _model(db, request.base_power_params_ref) if request.base_power_params_ref else None
    row = get_evidence(db, request.cpu_profile_ref) if request.cpu_profile_ref and request.cpu_profile is None else None
    scope = (str(row.scenario_ref), str(row.variant_ref)) if row is not None and row.scenario_ref and row.variant_ref else None
    return _RebalanceData(profile, target, base, scope)


def _rebalance_inputs(db: Session, request: CpuRebalanceRequest, *, coupling_base: dict[str, Any] | None = None,
                      prepared: _RebalanceData | None = None
                      ) -> tuple[Any, CpuPowerModel, CpuPowerModel | None, RebalanceSpec, dict[str, Any] | None, bool]:
    """DB-side half of a rebalance: profile, models, Timing Budget coupling and the search spec.

    ``coupling_base``: a ``timing_stretch`` result of the same variant (uniform growth only) reused by a sweep.
    """
    data = prepared or _rebalance_data(db, request)
    coupling, enforce = _timing_coupling(db, request, data, coupling_base)
    spec = RebalanceSpec(**_sweep_fields(request), pool=tuple(request.pool),
                         movable=tuple(request.movable) if request.movable is not None else None,
                         locks=dict(request.locks), co_move=tuple(tuple(g) for g in request.co_move),
                         verify_k=request.verify_k, max_exhaustive=request.max_exhaustive,
                         stretch_budgets=dict(coupling["stretch"]) if coupling and enforce else {},
                         serial_stages=coupling_stages(coupling))
    return data.profile, data.target, data.base, spec, coupling, enforce


def _timing_coupling(db: Session, request: CpuSweepRequest, data: _RebalanceData,
                     coupling_base: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, bool]:
    """The Timing Budget of the profile's variant: enforced as task budgets (stage_slack) or only reported (off)."""
    enforce = request.timing_coupling != "off"
    coupling = None
    if enforce and request.cpu_profile is not None:
        raise UnprocessableError("timing_coupling needs a stored measurement profile, not an inline CPU profile")
    if data.scope is not None:
        try:
            coupling = (scale_coupling(coupling_base, request.default_growth) if coupling_base is not None and not request.growth
                        else timing_stretch(db, *data.scope, statistic=request.timing_statistic,
                                            runtime_scale=request.default_growth, growth=request.growth))
            if not math.isclose(coupling["period_ms"], 1000.0 / request.fps, rel_tol=1e-3):
                if enforce:
                    raise UnprocessableError("timing coupling: CPU fps does not match the scenario variant")
                coupling = None
        except (NotFoundError, UnprocessableError) as exc:
            if enforce:
                raise UnprocessableError(f"timing coupling: {exc}") from exc
    elif enforce:
        raise UnprocessableError("timing_coupling needs a cpu_profile_ref measured on a scenario variant")
    return coupling, enforce


def _rebalance_compute(profile: Any, target: CpuPowerModel, base: CpuPowerModel | None, fps: float,
                       spec: RebalanceSpec) -> dict[str, Any]:
    """Pure compute half (no DB) — runs in a sweep worker process."""
    try:
        return cpu_rebalance(profile, target=target, base=base, fps=fps, spec=spec)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc


def _rebalance_finish(result: dict[str, Any], coupling: dict[str, Any] | None, enforce: bool) -> dict[str, Any]:
    if coupling:
        coupling["enforced"] = enforce
        ref = result["reference"]
        matched = sorted(t for t in coupling["stretch"] if t in (ref.get("task_ms") or {}))
        coupling["matched_tasks"] = matched
        coupling["unmatched_tasks"] = sorted(set(coupling["stretch"]) - set(matched))
        coupling["impact"] = {"reference": timing_impact(coupling, ref, ref),
                              "best": timing_impact(coupling, ref, result["best"]) if result.get("best") else None}
        for c in result.get("cases") or []:
            rows = timing_impact(coupling, ref, c)
            c["timing_slack_ms"] = min((r["slack_ms"] for r in rows), default=None)
        result["timing_coupling"] = coupling
    return result


BUILTIN_BW_MW_PER_MBS = 80.0 / 1000.0   # bw_power builtin: coeff 80 mW per GB/s, LLC weight 1


def bw_coefficient(db: Session, cpu_profile_ref: str | None) -> dict[str, Any]:
    """mW per MB/s for CPU → DRAM traffic (CPU-09): the BW model of the profile variant's registered
    prediction (IP BW mW / IP BW MB/s — same coefficient · LLC weight as the exploration), else builtin."""
    from scenario_db.db.models.exploration import Prediction

    row = get_evidence(db, cpu_profile_ref) if cpu_profile_ref else None
    if row is not None and row.scenario_ref and row.variant_ref:
        p = (db.query(Prediction).filter_by(scenario_ref=row.scenario_ref, variant_ref=row.variant_ref, status="current")
             .one_or_none())
        metrics: dict[str, Any] = dict(p.metrics or {}) if p is not None else {}
        pw: dict[str, Any] = metrics.get("power") or {}
        mbs = float(metrics.get("bw_ip_mbs") or 0.0)
        if p is not None and mbs > 0 and pw.get("bw_ip_mw") is not None:
            return {"mw_per_mbs": round(float(pw["bw_ip_mw"]) / mbs, 6), "source": "prediction", "prediction_ref": p.id,
                    "bw_power_model": (metrics.get("model_lineage") or {}).get("bw_power_model")}
    return {"mw_per_mbs": BUILTIN_BW_MW_PER_MBS, "source": "builtin", "prediction_ref": None, "bw_power_model": "builtin"}


def with_bw_power(result: dict[str, Any], coeff: dict[str, Any]) -> dict[str, Any]:
    """CPU + DSU + CPU-caused BW power for the reference and the best split (in place)."""
    mbs = result.get("cpu_bw_mbs")
    bw = round(float(mbs) * coeff["mw_per_mbs"], 2) if mbs is not None else None
    ref = (result.get("reference") or {}).get("total_mw")
    best = (result.get("best") or {}).get("total_mw")
    result["bw_power"] = coeff | {"cpu_bw_mbs": mbs, "bw_mw": bw,
                                  "reference_total_mw": round(ref + bw, 2) if ref is not None and bw is not None else None,
                                  "best_total_mw": round(best + bw, 2) if best is not None and bw is not None else None}
    return result


def run_cpu_rebalance(db: Session, request: CpuRebalanceRequest, *, coupling_base: dict[str, Any] | None = None) -> CpuWhatIfResponse:
    """``coupling_base``: a ``timing_stretch`` result of the same variant (uniform growth only) reused by a sweep."""
    profile, target, base, spec, coupling, enforce = _rebalance_inputs(db, request, coupling_base=coupling_base)
    release_read_connection(db)
    result = _rebalance_finish(_rebalance_compute(profile, target, base, request.fps, spec), coupling, enforce)
    result["timing_mode"] = request.timing_coupling
    if request.latency_trade and enforce and coupling:
        free = _rebalance_compute(profile, target, base, request.fps, replace(spec, stretch_budgets={}))
        result["latency_trade"] = latency_trade(coupling, result, free.get("best"))
    with_bw_power(result, bw_coefficient(db, request.cpu_profile_ref if request.cpu_profile is None else None))
    return CpuWhatIfResponse(profile_ref=profile.evidence_ref, power_params_ref=request.power_params_ref, result=result)


def run_cpu_whatif(db: Session, request: CpuWhatIfRequest) -> CpuWhatIfResponse:
    profile = _profile(db, request)
    target = _model(db, request.power_params_ref)
    base = _model(db, request.base_power_params_ref) if request.base_power_params_ref else None
    spec = WhatIfSpec(
        growth=request.growth, default_growth=request.default_growth, candidates=request.candidates,
        budgets_ms=request.budgets_ms, util_cap=request.util_cap, power_gating_eff=request.power_gating_eff,
        cpu_bw_scale=request.cpu_bw_scale, max_cases=request.max_cases,
    )
    release_read_connection(db)
    try:
        result = cpu_whatif(profile, target=target, base=base, fps=request.fps, spec=spec)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return CpuWhatIfResponse(profile_ref=profile.evidence_ref, power_params_ref=request.power_params_ref, result=result)


def list_cpu_inputs(db: Session) -> dict:
    """Topologies and measurements that carry a per-frame CPU profile (for pickers)."""
    from scenario_db.db.models.evidence import Evidence

    def clusters_of(params: Any) -> list[str]:
        cpu = (params or {}).get("cpu") or {}
        return [str(c.get("name")) for c in cpu.get("clusters") or [] if isinstance(c, dict)]

    topologies = []
    for prow in db.query(PowerModelParamsRow).order_by(PowerModelParamsRow.soc_ref, PowerModelParamsRow.id).all():
        names = clusters_of(prow.params)
        if names:
            topologies.append({"id": prow.id, "version": prow.version, "soc_ref": prow.soc_ref, "clusters": names})
    profiles: list[dict[str, Any]] = []
    for row in db.query(Evidence).filter(Evidence.kind == "evidence.measurement").all():
        obs: list[Any] = list(row.metric_observations or [])
        if any(isinstance(o, dict) and str(o.get("metric_id", "")).endswith("_pf") for o in obs):
            # task -> dominant measured cluster (for the placement matrix)
            cycles: dict[str, tuple[str, float]] = {}
            threads: dict[str, set[str]] = {}
            for o in obs:
                if isinstance(o, dict) and o.get("metric_id") == "cpu.thread_cycles_pf":
                    ref = str((o.get("scope") or {}).get("ref", ""))
                    head, _, thread = ref.partition("#")
                    threads.setdefault(head.rpartition("@")[0], set()).add(thread)
                scope = o.get("scope") or {} if isinstance(o, dict) else {}
                if isinstance(o, dict) and o.get("metric_id") == "cpu.cycles_pf" and scope.get("kind") == "task_cluster":
                    task, _, cluster = str(scope.get("ref", "")).rpartition("@")
                    value = float(o.get("value") or 0.0)
                    if task and value > cycles.get(task, ("", -1.0))[1]:
                        cycles[task] = (cluster, value)
            from scenario_db.api.services.calibration import data_origin

            profiles.append({"id": row.id, "scenario_ref": row.scenario_ref, "variant_ref": row.variant_ref,
                             "project_ref": row.project_ref,
                             # CPU-05: where the profile came from (synthetic must not read as a silicon capture)
                             "origin": data_origin(getattr(row, "provenance", None)),
                             "measured_at": row.measured_at.isoformat() if getattr(row, "measured_at", None) else None,
                             "sw_baseline_ref": getattr(row, "sw_baseline_ref", None),
                             "silicon_rev": (getattr(row, "execution_context", None) or {}).get("silicon_rev"),
                             "tasks": [{"task": t, "cluster": c, "threads": len(threads.get(t, ())) or None}
                                       for t, (c, _) in sorted(cycles.items())]})
    return {"topologies": topologies, "profiles": sorted(profiles, key=lambda p: p["id"])}


def resolve_cpu_profile(db: Session, scenario_id: str, variant_id: str | None, ref: str | None = None) -> tuple[Any, str | None]:
    """(CpuProfile, evidence id) for the profile CPU model: ``ref`` when given, else the variant's newest
    measurement with a per-frame CPU profile (silicon captures before synthetic). (None, None) when none."""
    from scenario_db.api.services.calibration import is_physical
    from scenario_db.db.models.evidence import Evidence

    if ref:
        row = get_evidence(db, ref)
        if row is None or row.kind != "evidence.measurement":
            raise NotFoundError(f"measurement evidence not found: {ref}")
        if row.scenario_ref != scenario_id or row.variant_ref != variant_id:
            raise UnprocessableError(f"measurement evidence {ref} does not belong to the requested scenario and variant")
        rows = [row]
    else:
        rows = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref == scenario_id,
                                          Evidence.variant_ref == variant_id)
                .order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all())
        rows.sort(key=lambda r: not is_physical(dict(r.provenance or {})))      # stable: newest physical first
    for row in rows:
        try:
            profile = cpu_profile_from_evidence(row, evidence_ref=str(row.id))
        except ValueError:
            continue
        if profile is not None and profile.tasks:
            return profile, str(row.id)
    if ref:
        raise UnprocessableError(f"measurement evidence {ref} has no per-frame CPU profile")
    return None, None


def with_cpu_profile(db: Session, options: Any, scenario_id: str, variant_id: str | None) -> Any:
    """TimingBudgetOptions with ``cpu_profile`` resolved when ``cpu_model == 'profile'`` (else unchanged)."""
    if getattr(options, "cpu_model", "flat") != "profile" or options.cpu_profile is not None:
        return options
    profile, ref = resolve_cpu_profile(db, scenario_id, variant_id, options.cpu_profile_ref)
    if profile is None:
        return options
    return options.model_copy(update={"cpu_profile": profile, "cpu_profile_ref": ref})


# ------------------------------------------------------------------- growth sweep (CPU-02..05)
def _split_view(s: dict[str, Any] | None) -> dict[str, Any] | None:
    if not s:
        return None
    return {"total_mw": round(float(s["total_mw"]), 2), "feasible": bool(s.get("feasible", True)),
            "mhz": {k: v for k, v in (s.get("mhz") or {}).items()},
            "mw": {k: round(float(v), 2) for k, v in (s.get("mw") or {}).items()},
            "moved": list(s.get("moved") or []), "min_slack_ms": s.get("min_slack_ms")}


def opp_events(points: list[dict[str, Any]], which: str) -> list[dict[str, Any]]:
    """Cluster frequency changes between consecutive growth points of ``which`` (reference / best)."""
    out = []
    for a, b in zip(points, points[1:], strict=False):
        sa, sb = a.get(which), b.get(which)
        if not sa or not sb:
            continue
        for cl, f in sb["mhz"].items():
            f0 = sa["mhz"].get(cl)
            if f0 is not None and f != f0 and cl != "dsu":
                out.append({"which": which, "growth_from": a["growth"], "growth_to": b["growth"], "cluster": cl,
                            "mhz": [f0, f], "delta_mw": round(sb["total_mw"] - sa["total_mw"], 2)})
    return out


def growth_limits(points: list[dict[str, Any]], events: list[dict[str, Any]]) -> dict[str, Any]:
    """SW-growth tolerance = min(growth before the largest OPP step-up of the reference placement,
    growth at which a Timing Budget stage runs out of SW room)."""
    ups = [e for e in events if e["which"] == "reference" and e["mhz"][1] > e["mhz"][0]]
    step = max(ups, key=lambda e: e["delta_mw"], default=None)
    timing_at = None
    seen_stages: set[str] = set()
    for p in points:
        for st in p.get("stages") or []:
            if st["stage"] in seen_stages or st["sw_ms"] <= 0:
                continue
            seen_stages.add(st["stage"])
            # Per-task growth overrides stay fixed while default_growth is swept. Use the
            # observed affine SW response rather than scaling the fixed share with growth.
            other = next(((q, t) for q in points if q["growth"] > p["growth"]
                          for t in q.get("stages") or [] if t["stage"] == st["stage"]), None)
            slope = ((other[1]["sw_ms"] - st["sw_ms"]) / (other[0]["growth"] - p["growth"])
                     if other else st["sw_ms"] / p["growth"])
            if st["room_ms"] <= 0 or slope <= 0 and st["sw_ms"] > st["room_ms"]:
                g = 0.0
            elif slope > 0:
                g = max(0.0, p["growth"] + (st["room_ms"] - st["sw_ms"]) / slope)
            else:
                continue  # a fixed SW share within budget imposes no growth limit
            timing_at = g if timing_at is None else min(timing_at, g)
    cands = [x for x in (step["growth_from"] if step else None, timing_at) if x is not None]
    best_step = None
    if step:
        pa = next(p for p in points if p["growth"] == step["growth_from"])
        pb = next(p for p in points if p["growth"] == step["growth_to"])
        if pa.get("best") and pb.get("best"):
            best_step = round(pb["best"]["total_mw"] - pa["best"]["total_mw"], 2)
    return {"opp_step": step, "opp_step_best_mw": best_step, "timing_at": round(timing_at, 3) if timing_at is not None else None,
            "tolerance": round(min(cands), 3) if cands else None,
            "binding": None if not cands else ("timing" if timing_at is not None and timing_at == min(cands) else "opp")}


def run_cpu_rebalance_sweep(db: Session, request: Any) -> dict[str, Any]:
    import time

    from scenario_db.api.schemas.cpu import CpuRebalanceRequest as _Req

    t0 = time.perf_counter()
    base = request.model_dump(exclude={"growths"})
    points: list[dict[str, Any]] = []
    growths = sorted(set(round(float(x), 4) for x in request.growths))
    # the Timing Budget does not depend on the growth except for the SW share: compute it once (uniform growth)
    coupling_base = None
    if request.timing_coupling != "off" and not request.growth and request.cpu_profile_ref and request.cpu_profile is None:
        row = get_evidence(db, request.cpu_profile_ref)
        if row is not None and row.scenario_ref and row.variant_ref:
            try:
                coupling_base = timing_stretch(db, str(row.scenario_ref), str(row.variant_ref),
                                               statistic=request.timing_statistic, runtime_scale=growths[0])
            except (NotFoundError, UnprocessableError):
                coupling_base = None  # the per-point call reports the error
    prepared = _rebalance_data(db, request)
    inputs = [_rebalance_inputs(db, _Req(**(base | {"default_growth": g})), coupling_base=coupling_base,
                               prepared=prepared) for g in growths]
    from dataclasses import replace as _replace

    release_read_connection(db)
    computed, workers = _compute_points([(i[0], i[1], i[2], request.fps, _replace(i[3], ratio_curves=False)) for i in inputs])
    coeff = bw_coefficient(db, request.cpu_profile_ref if request.cpu_profile is None else None)
    for g, inp, raw in zip(growths, inputs, computed, strict=True):
        res = _rebalance_finish(raw, inp[4], inp[5])
        strat = res.get("strategies") or {}
        coupling = res.get("timing_coupling") or {}
        impact = {r["stage"]: r for r in ((coupling.get("impact") or {}).get("reference") or [])}
        points.append({
            "growth": g, "reference": _split_view(res.get("reference")), "best": _split_view(res.get("best")),
            "strategies": [{"kind": r["kind"], "clusters": list(r["clusters"]), "total_mw": round(float(r["total_mw"]), 2),
                            "feasible": bool(r["feasible"]), "mhz": r.get("mhz") or {}} for r in strat.get("rows") or []],
            "winner": strat.get("winner"), "big_gain_mw": ((strat.get("big_check") or {}).get("best") or {}).get("delta_mw"),
            "cpu_bw_mbs": res.get("cpu_bw_mbs"),
            "bw_mw": round(float(res["cpu_bw_mbs"]) * coeff["mw_per_mbs"], 2) if res.get("cpu_bw_mbs") is not None else None,
            "feasible_count": res.get("feasible_count"),
            "stages": [{"stage": s["stage"], "sw_ms": s["sw_ms"], "room_ms": s["room_ms"], "slack_ms": s["slack_ms"],
                        "ok": (impact.get(s["stage"]) or {}).get("ok", s["slack_ms"] >= 0)} for s in coupling.get("stages") or []],
        })
    events = opp_events(points, "reference") + opp_events(points, "best")
    return {"profile_ref": request.cpu_profile_ref, "power_params_ref": request.power_params_ref, "fps": request.fps,
            "points": points, "events": events, "limits": growth_limits(points, events),
            "elapsed_ms": round(1000 * (time.perf_counter() - t0)), "workers": workers, "bw_power": coeff}


# ------------------------------------------------------------------- sweep worker pool
_POOL: Any = None
_POOL_SIZE = 0
_POOL_USERS = 0
_POOL_FAILED = False
_POOL_IDLE = Condition(RLock())


def _sweep_workers(n_points: int) -> int:
    import os

    from scenario_db.config import get_settings

    configured = get_settings().cpu_sweep_workers
    cpus = os.cpu_count() or 1
    want = configured if configured > 0 else min(cpus, 8)
    return max(1, min(want, n_points))


def _pool(size: int) -> Any:
    """Persistent process pool (forkserver: workers do not inherit the API's threads / DB connections)."""
    global _POOL, _POOL_SIZE, _POOL_FAILED
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    with _POOL_IDLE:
        # A batch owns its executor until every submitted future has stopped. Never
        # resize underneath another request or overlap old and replacement workers.
        while _POOL_USERS and (_POOL_FAILED or _POOL_SIZE < size):
            _POOL_IDLE.wait()
        if _POOL is None or _POOL_FAILED or _POOL_SIZE < size:
            if _POOL is not None:
                _POOL.shutdown(wait=True, cancel_futures=True)
            _POOL = None
            _POOL_SIZE = 0
            method = "forkserver" if "forkserver" in mp.get_all_start_methods() else "spawn"
            _POOL = ProcessPoolExecutor(max_workers=size, mp_context=mp.get_context(method))
            _POOL_SIZE = size
            _POOL_FAILED = False
        return _POOL


@contextmanager
def _pool_batch(size: int):
    global _POOL_USERS
    with _POOL_IDLE:
        pool = _pool(size)
        _POOL_USERS += 1
    try:
        yield pool
    finally:
        with _POOL_IDLE:
            _POOL_USERS -= 1
            _POOL_IDLE.notify_all()


def _retire_cpu_pool(expected: Any = None) -> None:
    global _POOL, _POOL_SIZE, _POOL_FAILED
    with _POOL_IDLE:
        while _POOL_USERS:
            if expected is not None and _POOL is not expected:
                return
            _POOL_IDLE.wait()
        if expected is not None and _POOL is not expected:
            return
        if _POOL is not None:
            _POOL.shutdown(wait=True, cancel_futures=True)
        _POOL = None
        _POOL_SIZE = 0
        _POOL_FAILED = False


def shutdown_cpu_pool() -> None:
    """Lifespan cleanup; outstanding batches finish before their executor is closed."""
    _retire_cpu_pool()


def _drain_points(futures: list[Any], completed: dict[int, dict[str, Any]]) -> None:
    """Cancel queued points and await running ones before any sequential fallback."""
    for future in futures:
        future.cancel()
    for index, future in enumerate(futures):
        if index in completed or future.cancelled():
            continue
        try:
            completed[index] = future.result()
        except Exception:  # failed points are recomputed by the original fallback
            pass


def _compute_points(jobs: list[tuple[Any, CpuPowerModel, CpuPowerModel | None, float, RebalanceSpec]]
                    ) -> tuple[list[dict[str, Any]], int]:
    """Rebalance of each sweep point; in parallel processes when more than one worker is allowed.

    Any pool failure (pickling, a broken worker) falls back to the sequential path so the result never
    depends on the deployment's process limits."""
    global _POOL_FAILED
    workers = _sweep_workers(len(jobs))
    completed: dict[int, dict[str, Any]] = {}
    if workers > 1 and len(jobs) >= 3:
        pool = None
        try:
            with _pool_batch(workers) as pool:
                futures: list[Any] = []
                try:
                    for job in jobs:
                        futures.append(pool.submit(_rebalance_compute, *job))
                    for index, future in enumerate(futures):
                        completed[index] = future.result()
                    return [completed[i] for i in range(len(jobs))], workers
                except UnprocessableError:
                    _drain_points(futures, completed)
                    raise
                except Exception:
                    with _POOL_IDLE:
                        if pool is _POOL:
                            _POOL_FAILED = True
                    _drain_points(futures, completed)
                    raise
        except UnprocessableError:
            raise
        except Exception:  # noqa: BLE001 - fall back to the in-process path
            # Drain all leases before retiring this executor; a peer request may
            # still be collecting its own point results from it.
            if pool is not None:
                _retire_cpu_pool(pool)
    return [completed[i] if i in completed else _rebalance_compute(*job)
            for i, job in enumerate(jobs)], 1
