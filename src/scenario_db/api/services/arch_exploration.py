"""Architecture exploration runs -> predictions (current/superseded) -> review reports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from scenario_db.api.schemas.arch_exploration import (
    ArchExplorationRunRequest,
    ArchReportRequest,
    PromoteRequest,
)
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services.timing_budget import _load, _shim
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.exploration import ArchExplorationRun, ArchReport, Prediction
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.reporting.arch_report import build_snapshot, html_sha256, render_html
from scenario_db.sim.arch_exploration import ENGINE_REV, explore_variant, find_case, prediction_payload
from scenario_db.sim.power_attribution import attribute
from scenario_db.sim.service import _apply_config_profile, _graph_soc_ref
from scenario_db.sim.timing_budget import DERIVED_VARIANT_MARKERS


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp() -> str:
    return _now().strftime("%Y%m%d-%H%M%S%f")[:-3]


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


# ------------------------------------------------------------------- scope
def _scenarios(db: Session, request: ArchExplorationRunRequest) -> list[Scenario]:
    q = db.query(Scenario)
    if request.project_ref:
        q = q.filter(Scenario.project_ref == request.project_ref)
    rows = q.order_by(Scenario.id).all()
    if request.scenario_ids:
        wanted = set(request.scenario_ids)
        rows = [r for r in rows if r.id in wanted]
        missing = wanted - {r.id for r in rows}
        if missing:
            raise NotFoundError(f"scenario not found: {sorted(missing)}")
    if request.category:
        cat = request.category.lower()
        rows = [r for r in rows if cat in [c.lower() for c in _as_list((r.metadata_ or {}).get("category"))]]
    if not rows:
        raise NotFoundError("no scenario matches the exploration scope")
    if len({r.project_ref for r in rows}) != 1:
        raise UnprocessableError("one exploration run must belong to one project; narrow the scope")
    return rows


def _variant_ids(db: Session, scenario_id: str, request: ArchExplorationRunRequest) -> list[str]:
    rows = db.query(ScenarioVariant.id, ScenarioVariant.derived_from_variant).filter_by(
        scenario_id=scenario_id).order_by(ScenarioVariant.id).all()
    ids = [r[0] for r in rows if request.include_derived or not r[1]]
    if not request.include_derived:
        ids = [i for i in ids if not any(m in i for m in DERIVED_VARIANT_MARKERS)]
    if request.variant_ids is not None:
        ids = [i for i in ids if i in set(request.variant_ids)]
    return ids


# ------------------------------------------------------------------- runs
def run_exploration(db: Session, request: ArchExplorationRunRequest, user: str | None = None) -> dict[str, Any]:
    scenarios = _scenarios(db, request)
    plan = [(s, v) for s in scenarios for v in _variant_ids(db, s.id, request)]
    if not plan:
        raise NotFoundError("exploration scope has no variants")
    if len(plan) > request.max_variants:
        raise UnprocessableError(f"exploration scope has {len(plan)} variants > max_variants {request.max_variants}")
    variants: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    soc_ref = request.soc_ref
    dvfs_ref: str | None = None
    remaining_cases = 2_000_000
    for scenario, variant_id in plan:
        if remaining_cases <= 0:
            raise UnprocessableError("exploration exceeds 2000000 total cases; narrow the scope")
        tb = TimingBudgetRequest(
            scenario_id=scenario.id, variant_id=variant_id, config=request.config,
            config_profile_ref=request.config_profile_ref, dvfs_tables=request.dvfs_tables,
            dvfs_table_ref=request.dvfs_table_ref, soc_ref=request.soc_ref,
            dvfs_version=request.dvfs_version, use_default_dvfs=request.use_default_dvfs,
        )
        shim = _shim(tb, variant_id)
        _apply_config_profile(db, shim)
        try:
            graph, tables, ref = _load(db, shim, request.use_default_dvfs)
            bounded_spec = request.spec.model_copy(update={
                "max_cases_per_variant": min(request.spec.max_cases_per_variant, remaining_cases),
            })
            summary = explore_variant(graph, bounded_spec, config=shim.config, dvfs_tables=tables)
        except (LookupError, ValueError) as exc:
            errors.append({"scenario_id": scenario.id, "variant_id": variant_id, "error": str(exc)[:300]})
            continue
        soc_ref = soc_ref or _graph_soc_ref(graph)
        dvfs_ref = dvfs_ref or ref
        remaining_cases -= summary["counts"]["cases"]
        summary["dvfs_table_ref"] = ref
        variants.append(summary)
    if not variants:
        raise UnprocessableError(f"every variant failed: {errors[:3]}")
    names = sorted({str((s.metadata_ or {}).get("name") or s.id) for s in scenarios})
    scenario_type = request.scenario_type or request.category or " + ".join(names)
    counts = {
        "variants": len(variants), "errors": len(errors),
        "spec_ok": sum(1 for v in variants if v["spec_ok"]),
        "cases": sum(v["counts"]["cases"] for v in variants),
        "eligible_cases": sum(v["counts"]["eligible"] for v in variants),
        "verified": sum(1 for v in variants if ((v.get("recommended") or {}).get("verified") or {}).get("ok")),
    }
    rec = [v["recommended"]["total_mw"] for v in variants if v.get("recommended")]
    counts["recommended_power_mw"] = [min(rec), max(rec)] if rec else None
    ihash = hashlib.sha256(json.dumps(sorted(v["input_hash"] for v in variants)).encode()).hexdigest()
    row = ArchExplorationRun(
        id=f"EXP-{uuid4().hex}",
        title=request.title or f"{scenario_type} exploration",
        scenario_type=scenario_type,
        project_ref=request.project_ref or scenarios[0].project_ref,
        soc_ref=soc_ref,
        spec=request.spec.model_dump(mode="json") | {"scenario_ids": [s.id for s in scenarios], "category": request.category},
        variants=variants, errors=errors, summary=counts, dvfs_table_ref=dvfs_ref,
        engine_rev=ENGINE_REV, input_hash=ihash, created_by=user, created_at=_now(),
    )
    db.add(row)
    db.commit()
    return run_detail(row)


def _run_meta(row: ArchExplorationRun) -> dict[str, Any]:
    return {
        "id": row.id, "title": row.title, "scenario_type": row.scenario_type, "project_ref": row.project_ref,
        "soc_ref": row.soc_ref, "dvfs_table_ref": row.dvfs_table_ref, "engine_rev": row.engine_rev,
        "summary": row.summary, "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def run_detail(row: ArchExplorationRun) -> dict[str, Any]:
    return _run_meta(row) | {"spec": row.spec, "variants": row.variants, "errors": row.errors}


def list_runs(db: Session, *, scenario_type: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    q = db.query(ArchExplorationRun)
    if scenario_type:
        q = q.filter(ArchExplorationRun.scenario_type == scenario_type)
    return [_run_meta(r) for r in q.order_by(ArchExplorationRun.created_at.desc()).limit(limit).all()]


def get_run(db: Session, run_id: str) -> ArchExplorationRun:
    row = db.get(ArchExplorationRun, run_id)
    if row is None:
        raise NotFoundError(f"exploration run not found: {run_id}")
    return row


# ------------------------------------------------------------------- predictions
def _pred_dict(p: Prediction, *, metrics: bool = True) -> dict[str, Any]:
    out = {
        "id": p.id, "scenario_id": p.scenario_ref, "variant_id": p.variant_ref, "project_ref": p.project_ref,
        "status": p.status, "run_id": p.exploration_run_ref, "case_key": p.case_key,
        "selection_rule": p.selection_rule, "selected_by": p.selected_by, "selected_by_user": p.selected_by_user,
        "reason": p.reason, "input_hash": p.input_hash, "dvfs_table_ref": p.dvfs_table_ref,
        "supersedes": p.supersedes_ref, "created_at": p.created_at.isoformat() if p.created_at else None,
    }
    if metrics:
        out["metrics"] = p.metrics
    return out


def promote(db: Session, request: PromoteRequest, user: str | None = None) -> dict[str, Any]:
    run = get_run(db, request.run_id)
    summaries = [v for v in run.variants if request.scenario_id is None or v["scenario_id"] == request.scenario_id]
    if request.variant_ids is not None and request.scenario_id is None:
        for vid in request.variant_ids:
            if sum(v["variant_id"] == vid for v in summaries) > 1:
                raise UnprocessableError("ambiguous variant_id; specify scenario_id")
    targets = [v for v in summaries if (v["variant_id"] in request.variant_ids
               if request.variant_ids is not None else v["spec_ok"])]
    # Lock the stable variant row, including the first promotion when no prediction exists.
    # Acquire all locks in canonical order to avoid deadlocks between overlapping requests.
    for summary in sorted(targets, key=lambda v: (v["scenario_id"], v["variant_id"])):
        variant = db.query(ScenarioVariant).filter_by(
            scenario_id=summary["scenario_id"], id=summary["variant_id"]).with_for_update().one_or_none()
        if variant is None:
            raise UnprocessableError("explored variant no longer exists")
    promoted, skipped = [], []
    for vid in dict.fromkeys(request.variant_ids or []):
        if not any(v["variant_id"] == vid for v in targets):
            skipped.append({"variant_id": vid, "reason": "variant not in run"})
    for summary in targets:
        vid = summary["variant_id"]
        case, rule = find_case(summary, request.case_key)
        if case is None:
            skipped.append({"variant_id": vid, "reason": "no eligible case" if request.case_key is None else "case_key not found"})
            continue
        if rule != "auto:min-power" and not request.reason:
            raise UnprocessableError("a non-default case needs a reason")
        if rule != "auto:min-power" and not case.get("eligible", True):
            raise UnprocessableError("selected case is not eligible (spec)")
        if case.get("verified") and not case["verified"]["ok"]:
            raise UnprocessableError("selected case failed re-simulation verification")
        metrics = prediction_payload(summary["objective_slice"], case, summary["buffers"])
        metrics |= {"dvfs_table_ref": summary.get("dvfs_table_ref"), "exploration_run_ref": run.id,
                    "design_conditions": summary.get("design_conditions"),
                    "distribution": summary["distribution"], "alternatives": len(summary.get("alternatives") or []),
                    "eligible_cases": summary["counts"]["eligible"], "verified": case.get("verified")}
        prev = (db.query(Prediction)
                .filter_by(scenario_ref=summary["scenario_id"], variant_ref=vid, status="current").one_or_none())
        if prev is not None:
            prev.status = "superseded"
            db.flush()
        pred = Prediction(
            id=f"PRED-{uuid4().hex}",
            scenario_ref=summary["scenario_id"], variant_ref=vid, project_ref=run.project_ref,
            status="current", exploration_run_ref=run.id, case_key=case["key"], selection_rule=rule,
            selected_by="auto" if rule == "auto:min-power" else "user", selected_by_user=user,
            reason=request.reason, metrics=metrics, input_hash=summary["input_hash"],
            dvfs_table_ref=summary.get("dvfs_table_ref"), supersedes_ref=prev.id if prev else None,
            created_at=_now(),
        )
        db.add(pred)
        db.flush()
        promoted.append(_pred_dict(pred, metrics=False) | {"total_mw": metrics["power"]["total_mw"]})
    db.commit()
    return {"run_id": run.id, "promoted": promoted, "skipped": skipped}


def board(db: Session, *, scenario_id: str | None = None, project_ref: str | None = None) -> dict[str, Any]:
    q = db.query(Prediction).filter(Prediction.status == "current")
    if scenario_id:
        q = q.filter(Prediction.scenario_ref == scenario_id)
    if project_ref:
        q = q.filter(Prediction.project_ref == project_ref)
    current = q.order_by(Prediction.scenario_ref, Prediction.variant_ref).all()
    prev_ids = [p.supersedes_ref for p in current if p.supersedes_ref]
    prev = {p.id: p for p in db.query(Prediction).filter(Prediction.id.in_(prev_ids)).all()} if prev_ids else {}
    runs = {r.id: r for r in db.query(ArchExplorationRun).filter(
        ArchExplorationRun.id.in_({p.exploration_run_ref for p in current})).all()} if current else {}
    rows = []
    for p in current:
        m = p.metrics
        old = prev.get(p.supersedes_ref) if p.supersedes_ref else None
        run = runs.get(p.exploration_run_ref)
        rows.append(_pred_dict(p, metrics=False) | {
            "run_title": run.title if run else None, "run_created_at": run.created_at.isoformat() if run and run.created_at else None,
            "fps": m.get("fps"), "power": m["power"], "bw_mbs": m.get("bw_mbs"), "distribution": m.get("distribution"),
            "compression": m.get("compression"), "dvfs": m.get("dvfs"), "verdict": m.get("verdict"),
            "eligible_cases": m.get("eligible_cases"), "alternatives": m.get("alternatives"), "verified": m.get("verified"),
            "statistic": m.get("statistic"), "runtime_scale": m.get("runtime_scale"),
            "previous": ({"id": old.id, "total_mw": old.metrics["power"]["total_mw"],
                          "delta_mw": round(m["power"]["total_mw"] - old.metrics["power"]["total_mw"], 3)} if old else None),
        })
    return {"rows": rows}


def history(db: Session, scenario_id: str, variant_id: str) -> list[dict[str, Any]]:
    rows = (db.query(Prediction).filter_by(scenario_ref=scenario_id, variant_ref=variant_id)
            .order_by(Prediction.created_at.desc()).all())
    return [_pred_dict(p, metrics=False) | {"total_mw": p.metrics["power"]["total_mw"], "power": p.metrics["power"],
                                            "bw_mbs": p.metrics.get("bw_mbs")} for p in rows]


def get_prediction(db: Session, prediction_id: str) -> dict[str, Any]:
    p = db.get(Prediction, prediction_id)
    if p is None:
        raise NotFoundError(f"prediction not found: {prediction_id}")
    return _pred_dict(p)


def compare(db: Session, *, old_id: str | None = None, new_id: str | None = None,
            scenario_id: str | None = None, variant_id: str | None = None) -> dict[str, Any]:
    if new_id is None:
        if not (scenario_id and variant_id):
            raise UnprocessableError("give new_id or scenario_id + variant_id")
        cur = db.query(Prediction).filter_by(scenario_ref=scenario_id, variant_ref=variant_id, status="current").one_or_none()
        if cur is None:
            raise NotFoundError("no current prediction")
        new = cur
    else:
        got = db.get(Prediction, new_id)
        if got is None:
            raise NotFoundError(f"prediction not found: {new_id}")
        new = got
    old_ref = old_id or new.supersedes_ref
    if old_ref is None:
        raise NotFoundError("no previous prediction to compare")
    old = db.get(Prediction, old_ref)
    if old is None:
        raise NotFoundError(f"prediction not found: {old_ref}")
    if (old.scenario_ref, old.variant_ref) != (new.scenario_ref, new.variant_ref):
        raise UnprocessableError("predictions must belong to the same scenario and variant")
    return {"old": _pred_dict(old, metrics=False), "new": _pred_dict(new, metrics=False),
            "attribution": attribute(old.metrics, new.metrics)}


# ------------------------------------------------------------------- reports
def create_report(db: Session, request: ArchReportRequest, user: str | None = None) -> dict[str, Any]:
    run = get_run(db, request.run_id)
    vids = [(v["scenario_id"], v["variant_id"]) for v in run.variants]
    preds: dict[tuple[str, str], dict[str, Any]] = {}
    changes: dict[tuple[str, str], dict[str, Any]] = {}
    for sid, vid in vids:
        cur = db.query(Prediction).filter_by(scenario_ref=sid, variant_ref=vid, status="current").one_or_none()
        if cur is None or cur.exploration_run_ref != run.id:
            continue  # the report states predictions registered from this run only
        preds[(sid, vid)] = _pred_dict(cur)
        if cur.supersedes_ref:
            old = db.get(Prediction, cur.supersedes_ref)
            if old is not None:
                changes[(sid, vid)] = attribute(old.metrics, cur.metrics)
    run_dict = run_detail(run) | {"created_at": run.created_at}
    snapshot = build_snapshot(run_dict, preds, changes, _conditions(db, vids))
    title = request.title or f"{run.soc_ref or ''} {run.scenario_type} Architecture 검토".strip()
    html = render_html(title, snapshot)
    row = ArchReport(
        id=f"RPT-{uuid4().hex}", title=title, status=request.status, target_soc_ref=run.soc_ref,
        project_ref=run.project_ref, scenario_type=run.scenario_type, exploration_run_refs=[run.id],
        dvfs_table_ref=run.dvfs_table_ref, engine_rev=run.engine_rev, snapshot=snapshot,
        rendered_html=html, html_sha256=html_sha256(html), generated_by=user, generated_at=_now(),
    )
    db.add(row)
    db.commit()
    return report_detail(row)


def _conditions(db: Session, vids: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Resolved design_conditions (parent first, then own + override) and severity, for report categories."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for sid in {s for s, _ in vids}:
        rows = {r.id: r for r in db.query(ScenarioVariant).filter(ScenarioVariant.scenario_id == sid).all()}

        def dc(vid: str, depth: int = 0) -> dict[str, Any]:
            r = rows.get(vid)
            if r is None or depth > 8:
                return {}
            base = dc(r.derived_from_variant, depth + 1) if r.derived_from_variant else {}
            return {**base, **(r.design_conditions or {}), **(r.design_conditions_override or {})}

        for s_, vid in vids:
            if s_ == sid and vid in rows:
                out[(sid, vid)] = {"design_conditions": dc(vid), "severity": rows[vid].severity}
    return out


def _report_meta(r: ArchReport) -> dict[str, Any]:
    ss = (r.snapshot or {}).get("spec_summary") or {}
    return {"id": r.id, "title": r.title, "status": r.status, "target_soc_ref": r.target_soc_ref,
            "project_ref": r.project_ref, "scenario_type": r.scenario_type, "run_ids": r.exploration_run_refs,
            "dvfs_table_ref": r.dvfs_table_ref, "engine_rev": r.engine_rev, "html_sha256": r.html_sha256,
            "generated_by": r.generated_by, "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "spec_ok": ss.get("spec_ok"), "explored": ss.get("explored")}


def report_detail(r: ArchReport) -> dict[str, Any]:
    return _report_meta(r) | {"snapshot": r.snapshot}


def list_reports(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    return [_report_meta(r) for r in db.query(ArchReport).order_by(ArchReport.generated_at.desc()).limit(limit).all()]


def get_report(db: Session, report_id: str) -> ArchReport:
    r = db.get(ArchReport, report_id)
    if r is None:
        raise NotFoundError(f"report not found: {report_id}")
    return r


def set_report_status(db: Session, report_id: str, status: str) -> dict[str, Any]:
    r = get_report(db, report_id)
    r.status = status
    db.commit()
    return _report_meta(r)


def report_stale(db: Session, report_id: str) -> dict[str, Any]:
    """Current predictions that differ from the frozen snapshot (-> regenerate)."""
    r = get_report(db, report_id)
    changed = []
    for row in (r.snapshot or {}).get("scenarios", []):
        cur = db.query(Prediction).filter_by(scenario_ref=row["scenario_id"], variant_ref=row["variant_id"],
                                             status="current").one_or_none()
        if (cur.id if cur else None) != row.get("prediction_id"):
            changed.append({"variant_id": row["variant_id"], "snapshot": row.get("prediction_id"),
                            "current": cur.id if cur else None})
    return {"report_id": r.id, "stale": bool(changed), "changed": changed}
