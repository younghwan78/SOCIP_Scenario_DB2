from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.api.schemas.cpu import CpuRebalanceRequest, CpuSweepRequest, CpuWhatIfRequest, CpuWhatIfResponse
from scenario_db.db.models.capability import PowerModelParams as PowerModelParamsRow
from scenario_db.db.repositories.evidence import get_evidence
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.sim.cpu_power import CpuPowerModel
from scenario_db.sim.cpu_profile import cpu_profile_from_evidence
from scenario_db.sim.cpu_rebalance import RebalanceSpec, cpu_rebalance
from scenario_db.sim.cpu_sched import SweepSpec, cpu_sweep
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
    profile = _profile(db, request)
    target = _model(db, request.power_params_ref)
    base = _model(db, request.base_power_params_ref) if request.base_power_params_ref else None
    spec = SweepSpec(**_sweep_fields(request))
    try:
        result = cpu_sweep(profile, target=target, base=base, fps=request.fps, spec=spec)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
    return CpuWhatIfResponse(profile_ref=profile.evidence_ref, power_params_ref=request.power_params_ref, result=result)


def run_cpu_rebalance(db: Session, request: CpuRebalanceRequest) -> CpuWhatIfResponse:
    profile = _profile(db, request)
    target = _model(db, request.power_params_ref)
    base = _model(db, request.base_power_params_ref) if request.base_power_params_ref else None
    spec = RebalanceSpec(**_sweep_fields(request), pool=tuple(request.pool),
                         movable=tuple(request.movable) if request.movable is not None else None,
                         locks=dict(request.locks), co_move=tuple(tuple(g) for g in request.co_move),
                         verify_k=request.verify_k, max_exhaustive=request.max_exhaustive)
    try:
        result = cpu_rebalance(profile, target=target, base=base, fps=request.fps, spec=spec)
    except ValueError as exc:
        raise UnprocessableError(str(exc)) from exc
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
