"""Prediction ↔ measurement calibration views (read-only)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, literal, tuple_
from sqlalchemy.orm import Session, defer, load_only

from scenario_db.comparison.calibration import CATEGORIES, category_fit, compare_split, measured_split, pct
from scenario_db.db.models.capability import SimConfigProfile
from scenario_db.db.models.definition import Scenario
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import Prediction
from scenario_db.exceptions import NotFoundError, UnprocessableError


def _total(kpi: dict[str, Any] | None) -> dict[str, Any]:
    t = (kpi or {}).get("total_power_mw")
    if isinstance(t, dict):
        return {"mean": t.get("mean"), "std": t.get("std"), "p95": t.get("p95"), "ci_95": t.get("ci_95"), "n": t.get("n")}
    if isinstance(t, (int, float)):
        return {"mean": float(t), "std": None, "p95": None, "ci_95": None, "n": None}
    return {"mean": None, "std": None, "p95": None, "ci_95": None, "n": None}


DATA_ORIGINS = ("synthetic", "physical_capture", "unknown")


def data_origin(provenance: dict[str, Any] | None) -> str:
    """synthetic / physical_capture / unknown.

    An explicit ``provenance.data_origin`` wins. Legacy documents: the synthetic naming rules
    (see scripts/generate_rear_recording_evidence.py); a capture needs a recorded collection method
    *and* device; anything else is unknown and never counts as silicon evidence.
    """
    p = provenance or {}
    explicit = p.get("data_origin")
    if explicit in DATA_ORIGINS:
        return str(explicit)
    if str(p.get("collection_method") or "").startswith("synthetic") or p.get("device_id") == "SYNTHETIC":
        return "synthetic"
    if p.get("collection_method") and p.get("device_id"):
        return "physical_capture"
    return "unknown"


def is_synthetic(provenance: dict[str, Any] | None) -> bool:
    """Generated fixture, not a silicon capture."""
    return data_origin(provenance) == "synthetic"


def is_physical(provenance: dict[str, Any] | None) -> bool:
    return data_origin(provenance) == "physical_capture"


def _origin_bucket(provenance: dict[str, Any] | None) -> str:
    return {"synthetic": "synthetic", "physical_capture": "measurement"}.get(data_origin(provenance), "unknown")


def _rail_map(db: Session, project_ref: str | None) -> tuple[dict[str, str], str | None]:
    if not project_ref:
        return {}, None
    q = db.query(SimConfigProfile)
    if project_ref:
        q = q.filter(SimConfigProfile.project_ref == project_ref)
    row = q.order_by(SimConfigProfile.version.desc(), SimConfigProfile.id).first()
    if row is None:
        return {}, None
    return dict(row.rail_domain_map or {}), str(row.id)


CONDITION_KEYS = ("silicon_rev", "sw_baseline_ref", "thermal", "power_state", "ambient_temp_c")


def compare_conditions(measured: dict[str, Any] | None, predicted: dict[str, Any] | None) -> dict[str, Any]:
    """Per condition: match / mismatch / unrecorded; overall equivalent / reference / unverified.

    ``reference`` = at least one recorded condition differs (Δ is a reference comparison only);
    ``unverified`` = nothing differs but some condition is missing on either side.
    """
    measured, predicted = measured or {}, predicted or {}
    items = []
    for k in CONDITION_KEYS:
        a, b = measured.get(k), predicted.get(k)
        status = "unrecorded" if a is None or b is None else "match" if a == b or str(a) == str(b) else "mismatch"
        items.append({"item": k, "measured": a, "predicted": b, "status": status})
    statuses = {i["status"] for i in items}
    overall = "reference" if "mismatch" in statuses else "unverified" if "unrecorded" in statuses else "equivalent"
    return {"overall": overall, "items": items}


def _measurement_rail_map(db: Session, m: Evidence, project_ref: str | None,
                          latest: dict[str, dict[str, str]] | None = None,
                          pinned_profiles: dict[str, SimConfigProfile] | None = None) -> tuple[dict[str, str], str | None, str]:
    """Rail map for one measurement: the profile pinned at capture, else the project's latest.

    Returns (map, profile id, basis) with basis ``pinned`` / ``latest`` / ``none`` so a comparison
    made with a rail definition newer than the capture is visible as such.
    """
    pinned = (m.provenance or {}).get("rail_domain_map_ref")
    if pinned:
        row = pinned_profiles.get(pinned) if pinned_profiles is not None else db.get(SimConfigProfile, pinned)
        if row is None:
            raise UnprocessableError(f"pinned rail map profile not found: {pinned}")
        if row.project_ref != project_ref:
            raise UnprocessableError(f"pinned rail map profile {pinned} belongs to another project")
        return dict(row.rail_domain_map or {}), str(row.id), "pinned"
    if latest is not None:
        rail = latest.get(project_ref or "")
        return (rail, None, "latest") if rail else ({}, None, "none")
    rail, ref = _rail_map(db, project_ref)
    return rail, ref, "latest" if rail else "none"


def _pinned_rail_profiles(db: Session, measurements: list[Evidence]) -> dict[str, SimConfigProfile]:
    refs = {(m.provenance or {}).get("rail_domain_map_ref") for m in measurements}
    refs.discard(None)
    refs.discard("")
    if not refs:
        return {}
    return {str(row.id): row for row in db.query(SimConfigProfile).options(load_only(
        SimConfigProfile.id, SimConfigProfile.project_ref, SimConfigProfile.rail_domain_map))
        .filter(SimConfigProfile.id.in_(refs)).all()}


def _rail_maps(db: Session, project_refs: set[str | None]) -> dict[str, dict[str, str]]:
    """Latest rail map per project in one query (same pick as ``_rail_map``)."""
    refs = {p for p in project_refs if p}
    if not refs:
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in (db.query(SimConfigProfile).filter(SimConfigProfile.project_ref.in_(refs))
                .order_by(SimConfigProfile.version.desc(), SimConfigProfile.id).all()):
        out.setdefault(row.project_ref, dict(row.rail_domain_map or {}))
    return out


def _sim_order(ev: Evidence) -> tuple[datetime, str]:
    timestamp = ev.measured_at or (ev.run_info or {}).get("timestamp")
    try:
        dt = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
        dt = dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt
    except ValueError:
        dt = None
    return dt or datetime.min.replace(tzinfo=timezone.utc), str(ev.id)


def _sim_evidence(db: Session, scenario: str, variant: str) -> list[Evidence]:
    return sorted(db.query(Evidence)
            .filter(Evidence.kind == "evidence.simulation", Evidence.scenario_ref == scenario, Evidence.variant_ref == variant)
            .all(), key=_sim_order)


def _current(db: Session, scenario: str, variant: str) -> Prediction | None:
    return (db.query(Prediction)
            .filter_by(scenario_ref=scenario, variant_ref=variant, status="current").one_or_none())


def _sim_split(ev: Evidence) -> dict[str, float] | None:
    """CPU/IP/BW split of a simulation evidence (None when it has no IP breakdown)."""
    pb = ev.power_breakdown or {}
    if not isinstance(pb, dict) or pb.get("ip") is None:
        return None

    def _mw(v: Any) -> float:
        return float(v.get("total_mw", 0.0)) if isinstance(v, dict) else float(v or 0.0)

    return {"cpu": _mw(pb.get("cpu")), "ip": _mw(pb.get("ip")), "bw": _mw(pb.get("memory"))}


def _pred_split(power: dict[str, Any]) -> dict[str, float]:
    return {"cpu": float(power.get("cpu_mw") or 0.0), "ip": float(power.get("hw_mw") or 0.0),
            "bw": float(power.get("bw_mw") or 0.0)}


def coverage(db: Session, scenario_id: str) -> dict[str, dict[str, Any]]:
    """Per variant: simulation evidence count, real / synthetic measurement count, current prediction."""
    out: dict[str, dict[str, Any]] = {}

    def row(v: str) -> dict[str, Any]:
        return out.setdefault(v, {"simulation": 0, "measurement": 0, "synthetic": 0, "unknown": 0, "current_prediction": None})

    for kind, variant, prov in (db.query(Evidence.kind, Evidence.variant_ref, Evidence.provenance)
                                .filter(Evidence.scenario_ref == scenario_id).all()):
        if kind == "evidence.simulation":
            row(variant)["simulation"] += 1
        elif kind == "evidence.measurement":
            row(variant)[_origin_bucket(prov)] += 1
    for p in db.query(Prediction).filter_by(scenario_ref=scenario_id, status="current").all():
        row(p.variant_ref)["current_prediction"] = {"id": p.id, "total_mw": (p.metrics or {}).get("power", {}).get("total_mw")}
    return out


def coverage_summary(db: Session) -> dict[str, dict[str, int]]:
    """Per scenario: distinct variants with simulation / real measurement / synthetic measurement / current prediction."""
    sets: dict[str, dict[str, set[str]]] = {}

    def bucket(scenario: str) -> dict[str, set[str]]:
        return sets.setdefault(scenario, {"simulation": set(), "measurement": set(), "synthetic": set(), "unknown": set(),
                                          "current_prediction": set()})

    for kind, scenario, variant, prov in db.query(Evidence.kind, Evidence.scenario_ref, Evidence.variant_ref, Evidence.provenance).all():
        if kind == "evidence.simulation":
            bucket(scenario)["simulation"].add(variant)
        elif kind == "evidence.measurement":
            bucket(scenario)[_origin_bucket(prov)].add(variant)
    for scenario, variant in db.query(Prediction.scenario_ref, Prediction.variant_ref).filter(Prediction.status == "current").all():
        bucket(scenario)["current_prediction"].add(variant)
    return {k: {n: len(v) for n, v in b.items()} for k, b in sets.items()}


def _fit(pred: dict[str, float] | None, meas_cat: dict[str, float] | None, total_delta: float | None) -> dict[str, Any] | None:
    """Category-level fit (U6): a total within 10% can hide -35% IP / +50% BW."""
    if pred is None or meas_cat is None:
        return None
    return category_fit(compare_split(pred, meas_cat), total_delta)


def list_measurements(db: Session, *, scenario_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(Evidence).filter(Evidence.kind == "evidence.measurement")
    if scenario_id:
        q = q.filter(Evidence.scenario_ref == scenario_id)
    measurements = q.order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all()
    scenario_ids = {m.scenario_ref for m in measurements}
    current = {(p.scenario_ref, p.variant_ref): p for p in db.query(Prediction).filter(
        Prediction.status == "current", Prediction.scenario_ref.in_(scenario_ids)).all()}
    simulations: dict[tuple[str, str], list[Evidence]] = {}
    # only the columns the comparison reads: timeline / DMA breakdowns can be megabytes per row
    sim_cols = load_only(Evidence.id, Evidence.scenario_ref, Evidence.variant_ref, Evidence.measured_at,
                         Evidence.run_info, Evidence.kpi, Evidence.power_breakdown)
    for ev in db.query(Evidence).options(sim_cols).filter(Evidence.kind == "evidence.simulation", Evidence.scenario_ref.in_(scenario_ids)).order_by(
        Evidence.measured_at.asc().nullsfirst(), Evidence.id).all():
        simulations.setdefault((ev.scenario_ref, ev.variant_ref), []).append(ev)
    for sims in simulations.values():
        sims.sort(key=_sim_order)
    scenario_project = {sid: pref for sid, pref in db.query(Scenario.id, Scenario.project_ref)
                        .filter(Scenario.id.in_(scenario_ids)).all()} if scenario_ids else {}
    rail_maps = _rail_maps(db, {m.project_ref or scenario_project.get(m.scenario_ref) for m in measurements})
    pinned_profiles = _pinned_rail_profiles(db, measurements)
    out = []
    for m in measurements:
        total = _total(m.kpi)
        rail_map, _, rail_basis = _measurement_rail_map(db, m, m.project_ref or scenario_project.get(m.scenario_ref),
                                                      rail_maps, pinned_profiles)
        meas_cat = measured_split(m.vdd_power, rail_map)["categories"] if m.vdd_power else None
        cur = current.get((m.scenario_ref, m.variant_ref))
        sims = simulations.get((m.scenario_ref, m.variant_ref), [])
        sim_total = _total(sims[-1].kpi)["mean"] if sims else None
        cur_total = cur.metrics["power"]["total_mw"] if cur else None
        ctx = m.execution_context or {}
        out.append({
            "id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref, "project_ref": m.project_ref,
            "measured_at": m.measured_at.isoformat() if m.measured_at else None,
            "silicon_rev": ctx.get("silicon_rev"), "sw_baseline_ref": m.sw_baseline_ref, "thermal": ctx.get("thermal"),
            "total": total, "fps": (m.kpi or {}).get("fps_effective"),
            "rails": len(m.vdd_power or {}), "synthetic": is_synthetic(m.provenance),
            "origin": data_origin(m.provenance), "rail_map_basis": rail_basis,
            "current_prediction": {"id": cur.id, "total_mw": cur_total, "delta_pct": pct(cur_total, total["mean"]),
                                   "category": _fit(_pred_split(cur.metrics["power"]), meas_cat, pct(cur_total, total["mean"]))} if cur else None,
            "simulation": {"id": sims[-1].id, "total_mw": sim_total, "delta_pct": pct(sim_total, total["mean"]), "count": len(sims),
                           "category": _fit(_sim_split(sims[-1]), meas_cat, pct(sim_total, total["mean"]))} if sims else None,
        })
    return out


def measurement_detail(db: Session, measurement_id: str) -> dict[str, Any]:
    m = db.get(Evidence, measurement_id)
    if m is None or m.kind != "evidence.measurement":
        raise NotFoundError(f"measurement evidence not found: {measurement_id}")
    scenario = db.get(Scenario, m.scenario_ref)
    project_ref = m.project_ref or (scenario.project_ref if scenario is not None else None)
    cur = _current(db, m.scenario_ref, m.variant_ref)
    return _detail(m, _measurement_rail_map(db, m, project_ref), cur, cur.metrics if cur is not None else None,
                   _sim_evidence(db, m.scenario_ref, m.variant_ref))


def measurement_detail_view(db: Session, measurement_id: str) -> dict[str, Any]:
    """``measurement_detail`` + the clock-domain residency view (calibration page)."""
    out = measurement_detail(db, measurement_id)
    out["clock_residency"] = clock_residency_of(db, db.get(Evidence, measurement_id))
    return out


def _cpu_domains(m: Any) -> set[str]:
    names = {str(e.get("cluster")) for e in (m.cpu_breakdown or []) if isinstance(e, dict) and e.get("cluster")}
    for o in m.metric_observations or []:
        if isinstance(o, dict) and str(o.get("metric_id", "")).startswith("cpu.freq_residency"):
            names.add(str((o.get("scope") or {}).get("ref", "")).rpartition("@")[0])
    return names


def _soc_of(db: Session, m: Any) -> str | None:
    from scenario_db.db.models.definition import Project

    project_ref = m.project_ref
    if not project_ref:
        scenario = db.get(Scenario, m.scenario_ref)
        project_ref = scenario.project_ref if scenario is not None else None
    project = db.get(Project, project_ref) if project_ref else None
    return (project.metadata_ or {}).get("soc_ref") if project is not None else None


def clock_residency_of(db: Session, m: Any, params_rows: list[Any] | None = None,
                       ip_rows: list[Any] | None = None) -> dict[str, Any] | None:
    """Clock residency view of one measurement (max OPP: CPU topology of the SoC, IP catalog for GPU …)."""
    from scenario_db.api.services.clock_residency import clock_residency_view, opp_max_from_ip_catalog, opp_max_from_params
    from scenario_db.db.models.capability import IpCatalog, PowerModelParams

    if not _cpu_domains(m) and not any(isinstance(o, dict) and ".freq_residency" in str(o.get("metric_id", ""))
                                       for o in m.metric_observations or []):
        return None
    soc = _soc_of(db, m)
    if params_rows is None:
        params_rows = db.query(PowerModelParams).all()
    if ip_rows is None:
        ip_rows = db.query(IpCatalog).options(load_only(IpCatalog.id, IpCatalog.capabilities, IpCatalog.compatible_soc)).all()
    same_soc = [r for r in params_rows if not soc or getattr(r, "soc_ref", None) == soc] or list(params_rows)
    opp_max = opp_max_from_ip_catalog(ip_rows, soc) | opp_max_from_params(same_soc, _cpu_domains(m))
    return clock_residency_view(m.metric_observations, m.cpu_breakdown, opp_max=opp_max)


def clock_residency_rows(db: Session, scenario_id: str | None = None) -> list[dict[str, Any]]:
    """One row per measurement with clock residency (variant / SW comparison table)."""
    from scenario_db.db.models.capability import PowerModelParams

    q = db.query(Evidence).options(load_only(
        Evidence.id, Evidence.scenario_ref, Evidence.variant_ref, Evidence.measured_at, Evidence.provenance,
        Evidence.execution_context, Evidence.metric_observations, Evidence.cpu_breakdown)).filter(
        Evidence.kind == "evidence.measurement")
    if scenario_id:
        q = q.filter(Evidence.scenario_ref == scenario_id)
    from scenario_db.db.models.capability import IpCatalog

    params_rows = db.query(PowerModelParams).all()
    ip_rows = db.query(IpCatalog).options(load_only(IpCatalog.id, IpCatalog.capabilities, IpCatalog.compatible_soc)).all()
    out = []
    for m in q.order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all():
        view = clock_residency_of(db, m, params_rows, ip_rows)
        if view is None:
            continue
        ctx = m.execution_context or {}
        out.append({"id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref,
                    "measured_at": m.measured_at.isoformat() if m.measured_at else None,
                    "sw_baseline_ref": ctx.get("sw_baseline_ref"), "synthetic": is_synthetic(m.provenance),
                    "domains": [{k: d[k] for k in ("domain_class", "class_label", "domain", "is_dsu", "active_ratio", "pass_jsd")}
                                | {"mean_mhz": (d["active"] or d["wall"])["mean_mhz"], "opp_max_mhz": d["opp_max_mhz"],
                                   "high_share": (d["active"] or d["wall"])["high_share"],
                                   "basis": "active" if d["active"] else "wall",
                                   "warns": sum(1 for n in d["notes"] if n["level"] == "warn")}
                                for d in view["domains"]]})
    return out


def measurement_details(db: Session, measurement_ids: list[str]) -> dict[str, dict[str, Any]]:
    """``measurement_detail`` for many measurements in a constant number of queries (report generation)."""
    if not measurement_ids:
        return {}
    ms = db.query(Evidence).filter(Evidence.id.in_(measurement_ids), Evidence.kind == "evidence.measurement").all()
    keys = {(m.scenario_ref, m.variant_ref) for m in ms}
    scen_project = dict(db.query(Scenario.id, Scenario.project_ref).filter(Scenario.id.in_({k[0] for k in keys})).all())
    cur_metrics = func.jsonb_build_object(literal("power"), Prediction.metrics["power"],
                                          literal("statistic"), Prediction.metrics["statistic"])
    currents = {(p.scenario_ref, p.variant_ref): (p, pm) for p, pm in db.query(Prediction, cur_metrics)
                .options(defer(Prediction.metrics))
                .filter(Prediction.status == "current", tuple_(Prediction.scenario_ref, Prediction.variant_ref).in_(keys)).all()}
    sims: dict[tuple[str, str], list[Evidence]] = {}
    for ev in (db.query(Evidence).options(load_only(
            Evidence.id, Evidence.scenario_ref, Evidence.variant_ref, Evidence.measured_at, Evidence.run_info,
            Evidence.kpi, Evidence.power_breakdown, Evidence.execution_context, Evidence.sw_baseline_ref))
            .filter(Evidence.kind == "evidence.simulation",
                    tuple_(Evidence.scenario_ref, Evidence.variant_ref).in_(keys)).all()):
        sims.setdefault((ev.scenario_ref, ev.variant_ref), []).append(ev)
    projects = {m.project_ref or scen_project.get(m.scenario_ref) for m in ms}
    pinned_profiles = _pinned_rail_profiles(db, ms)
    latest = {}
    for row in (db.query(SimConfigProfile).filter(SimConfigProfile.project_ref.in_({p for p in projects if p}))
                .order_by(SimConfigProfile.version.desc(), SimConfigProfile.id).all()):
        latest.setdefault(row.project_ref, (dict(row.rail_domain_map or {}), str(row.id)))
    out = {}
    for m in ms:
        project = m.project_ref or scen_project.get(m.scenario_ref)
        rail = (_measurement_rail_map(db, m, project, {}, pinned_profiles)
                if (m.provenance or {}).get("rail_domain_map_ref") else None)
        if rail is None or rail[2] != "pinned":
            lm = latest.get(project or "")
            rail = (lm[0], lm[1], "latest") if lm and lm[0] else ({}, None, "none")
        cur, cm = currents.get((m.scenario_ref, m.variant_ref), (None, None))
        out[m.id] = _detail(m, rail, cur, cm, sorted(sims.get((m.scenario_ref, m.variant_ref), []), key=_sim_order))
    return out


def _detail(m: Evidence, rail: tuple[dict[str, str], str | None, str], cur: Prediction | None,
            cur_metrics: dict[str, Any] | None, sims: list[Evidence]) -> dict[str, Any]:
    rail_map, profile_ref, rail_basis = rail
    split = measured_split(m.vdd_power, rail_map)
    total = _total(m.kpi)
    meas_cat = split["categories"]
    predictions: list[dict[str, Any]] = []
    if cur is not None and cur_metrics is not None:
        pw = cur_metrics["power"]
        predictions.append({
            "kind": "current", "id": cur.id, "label": "등록 예측 (current)", "run_id": cur.exploration_run_ref,
            "selection_rule": cur.selection_rule, "statistic": cur_metrics.get("statistic"),
            "total_mw": pw["total_mw"], "delta_pct": pct(pw["total_mw"], total["mean"]),
            "split": _pred_split(pw), "rows": compare_split(_pred_split(pw), meas_cat),
        })
    meas_ctx = dict(m.execution_context or {}) | ({"sw_baseline_ref": m.sw_baseline_ref} if m.sw_baseline_ref else {})
    for p in predictions:  # registered prediction: the model run records no device/thermal condition
        p["conditions"] = compare_conditions(meas_ctx, {})
    for ev in sims:
        t = _total(ev.kpi)["mean"]
        sp = _sim_split(ev)
        sim_ctx = dict(ev.execution_context or {}) | ({"sw_baseline_ref": ev.sw_baseline_ref} if ev.sw_baseline_ref else {})
        predictions.append({
            "kind": "simulation", "id": ev.id, "label": "Simulation evidence",
            "total_mw": t, "delta_pct": pct(t, total["mean"]), "split": sp,
            "rows": compare_split(sp, meas_cat) if sp else None,
            "conditions": compare_conditions(meas_ctx, sim_ctx),
        })
    sw = []
    for task in (m.sw_task_timing or []):
        if isinstance(task, dict):
            sw.append({k: task.get(k) for k in ("task", "mean_ms", "p95_ms", "max_ms", "min_ms", "count", "thread", "cluster", "timing_scope") if k in task})
    ctx = m.execution_context or {}
    return {
        "id": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref, "project_ref": m.project_ref,
        "measured_at": m.measured_at.isoformat() if m.measured_at else None,
        "context": {k: ctx.get(k) for k in ("silicon_rev", "thermal", "power_state", "ambient_temp_c", "sw_baseline_ref")},
        "synthetic": is_synthetic(m.provenance), "origin": data_origin(m.provenance),
        "derived_from": list(m.derived_from or []),
        "total": total, "fps": (m.kpi or {}).get("fps_effective"), "frame_latency": (m.kpi or {}).get("frame_latency_ms"),
        "measured": split, "rail_domain_map_ref": profile_ref, "rail_map_basis": rail_basis,
        "unexplained_mw": None if total["mean"] is None else round(float(total["mean"]) - split["rail_total_mw"], 3),
        "categories": list(CATEGORIES), "predictions": predictions, "sw_tasks": sw,
        "cpu_clusters": m.cpu_breakdown,
    }
