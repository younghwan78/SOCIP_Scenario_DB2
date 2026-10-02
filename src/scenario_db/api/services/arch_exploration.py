"""Architecture exploration runs -> predictions (current/superseded) -> review reports."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from scenario_db.api.schemas.arch_exploration import (
    ArchExplorationRunRequest,
    ArchReportRequest,
    PowerOptionReviewRequest,
    PromoteRequest,
)
from scenario_db.api.schemas.timing_budget import TimingBudgetRequest
from scenario_db.api.services.timing_budget import _load, _shim
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import (
    POWER_OPTION_STATUSES,
    ArchExplorationRun,
    ArchReport,
    PowerOptionReview,
    Prediction,
)
from scenario_db.exceptions import NotFoundError, UnprocessableError
from scenario_db.reporting.arch_conclusion import calibration_row, run_lineage
from scenario_db.reporting.arch_report import build_snapshot, html_sha256, render_html
from scenario_db.reporting.xlsx_export import report_sheets, write_xlsx
from scenario_db.sim.arch_exploration import ENGINE_REV, explore_variant, find_case, prediction_payload
from scenario_db.sim.power_attribution import attribute
from scenario_db.api.services.calibration import is_synthetic, measurement_detail
from scenario_db.api.services.failures import variant_failure
from scenario_db.sim.model_lineage import lineage_differences, run_model_lineage
from scenario_db.sim.service import _apply_config_profile, _check_power_params_scope, _graph_soc_ref
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
        stage = "load"
        try:
            graph, tables, ref = _load(db, shim, request.use_default_dvfs)
            bounded_spec = request.spec.model_copy(update={
                "max_cases_per_variant": min(request.spec.max_cases_per_variant, remaining_cases),
            })
            _check_power_params_scope(shim.config, graph)
            stage = "explore"
            summary = explore_variant(graph, bounded_spec, config=shim.config, dvfs_tables=tables)
            summary["model_lineage"] = run_model_lineage(shim.config)
        except Exception as exc:  # noqa: BLE001 - one variant must not abort the run
            errors.append(variant_failure(exc, variant_id=variant_id, scenario_id=scenario.id, stage=stage))
            continue
        soc_ref = soc_ref or _graph_soc_ref(graph)
        dvfs_ref = dvfs_ref or ref
        remaining_cases -= summary["counts"]["cases"] + summary["counts"].get("option_cases", 0)
        summary["dvfs_table_ref"] = ref
        variants.append(summary)
    if not variants:
        first = errors[0]
        raise UnprocessableError(
            f"every variant failed ({len(errors)}); first: {first['variant_id']} "
            f"[{first['stage']}/{first['category']}] {first['error'][:300]}"
        )
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
    opt = [v["power_options"] for v in variants if (v.get("power_options") or {}).get("status") == "ok"]
    best = [r["delta_mw"] for o in opt for r in o["results"] if r["key"] == o.get("best")]
    counts["power_options"] = {"variants": len(best), "sets": sum(len(o["results"]) for o in opt),
                               "cases": sum(o.get("cases", 0) for o in opt),
                               "best_saving_mw": [min(best), max(best)] if best else None}
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
                    "eligible_cases": summary["counts"]["eligible"], "verified": case.get("verified"),
                    "power_options": option_snapshot(summary.get("power_options"), case, rule),
                    "model_lineage": summary.get("model_lineage")}
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
    reviews = _reviews_by_scenario(db, {p.scenario_ref for p in current})
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
                          "delta_mw": round(m["power"]["total_mw"] - old.metrics["power"]["total_mw"], 3),
                          "lineage_changes": lineage_differences(old.metrics.get("model_lineage"),
                                                                 m.get("model_lineage"))} if old else None),
            "power_options": board_options(m.get("power_options"), reviews.get(p.scenario_ref, {}), p.variant_ref),
        })
    return {"rows": rows, "review_statuses": list(POWER_OPTION_STATUSES)}


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
    changes = lineage_differences(old.metrics.get("model_lineage"), new.metrics.get("model_lineage"))
    return {"old": _pred_dict(old, metrics=False), "new": _pred_dict(new, metrics=False),
            "attribution": attribute(old.metrics, new.metrics),
            # A model/coefficient/clock-basis change moves power with no design
            # change; the attribution above cannot tell the two apart.
            "lineage_changes": changes,
            "lineage_warning": (
                "model lineage differs (" + ", ".join(c["field"] for c in changes) + "); part of the delta "
                "comes from the model, not the scenario" if changes else None
            )}


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
    snapshot = build_snapshot(run_dict, preds, changes, _report_calibration(db, preds))
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


def _report_calibration(db: Session, preds: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest measurement per reported variant (real silicon preferred over synthetic) vs its registered prediction."""
    if not preds:
        return []
    keys = set(preds)
    found: dict[tuple[str, str], Evidence] = {}
    rows = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement",
                                      Evidence.scenario_ref.in_({sid for sid, _ in keys}))
            .order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all())
    for m in rows:
        key = (m.scenario_ref, m.variant_ref)
        if key not in keys:
            continue
        held = found.get(key)
        if held is None or (is_synthetic(held.provenance) and not is_synthetic(m.provenance)):
            found[key] = m
    out = []
    for (sid, vid), m in sorted(found.items()):
        row = calibration_row(vid, sid, measurement_detail(db, m.id), preds[(sid, vid)]["id"])
        if row is not None:
            out.append(row)
    return out


def _report_meta(r: ArchReport) -> dict[str, Any]:
    ss = (r.snapshot or {}).get("spec_summary") or {}
    return {"id": r.id, "title": r.title, "status": r.status, "target_soc_ref": r.target_soc_ref,
            "project_ref": r.project_ref, "scenario_type": r.scenario_type, "run_ids": r.exploration_run_refs,
            "dvfs_table_ref": r.dvfs_table_ref, "engine_rev": r.engine_rev, "html_sha256": r.html_sha256,
            "generated_by": r.generated_by, "generated_at": r.generated_at.isoformat() if r.generated_at else None,
            "spec_ok": ss.get("spec_ok"), "explored": ss.get("explored"),
            "review": (r.review_history or [None])[-1], "review_count": len(r.review_history or [])}


def report_detail(r: ArchReport) -> dict[str, Any]:
    return _report_meta(r) | {"snapshot": r.snapshot}


def list_reports(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    return [_report_meta(r) for r in db.query(ArchReport).order_by(ArchReport.generated_at.desc()).limit(limit).all()]


def get_report(db: Session, report_id: str) -> ArchReport:
    r = db.get(ArchReport, report_id)
    if r is None:
        raise NotFoundError(f"report not found: {report_id}")
    return r


def set_report_status(db: Session, report_id: str, status: str, *, reviewer: str | None = None,
                      note: str | None = None, user: str | None = None) -> dict[str, Any]:
    r = get_report(db, report_id)
    if status == "published" and (not (reviewer or "").strip() or not (note or "").strip()):
        raise UnprocessableError("publishing requires reviewer and note")
    r.status = status
    r.review_history = [*(r.review_history or []), {"status": status, "reviewer": (reviewer or "").strip() or None,
                                                    "note": (note or "").strip() or None, "by": user, "at": _now().isoformat()}]
    db.commit()
    return _report_meta(r)


def report_xlsx(db: Session, report_id: str) -> tuple[bytes, str]:
    r = get_report(db, report_id)
    meta = _report_meta(r)
    stamp = r.generated_at.strftime("%Y%m%d-%H%M") if r.generated_at else "report"
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{r.target_soc_ref or 'soc'}_{r.scenario_type}_{stamp}")[:80]
    return write_xlsx(report_sheets(r.snapshot or {}, meta)), f"{name}.xlsx"


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


# ------------------------------------------------------------------- power options
def option_snapshot(po: dict[str, Any] | None, case: dict[str, Any], rule: str) -> dict[str, Any] | None:
    """Power options frozen with a prediction. Deltas are relative to the variant's
    recommended case; a user-selected (non-default) case keeps them but says so."""
    if po is None:
        return None
    out = {k: po.get(k) for k in ("status", "notes", "sets", "max_sets", "best", "errors")}
    out["dimensions"] = [
        {k: d.get(k) for k in ("id", "kind", "label", "current", "node", "ip_ref")}
        | {"items": [{k: i.get(k) for k in ("key", "kind", "label", "value", "from", "iq_eval", "note",
                                           "unit_power_mw_mp", "from_unit_power_mw_mp", "ppc", "from_ppc",
                                           "source")} for i in d.get("items") or []]}
        for d in po.get("dimensions") or []
    ]
    out["results"] = po.get("results") or []
    out["reference"] = {"rule": rule, "case_key": case.get("key"),
                        "note": None if rule == "auto:min-power" else
                        "option deltas are relative to the auto (min-power) case, not the selected case"}
    return out


def _reviews_by_scenario(db: Session, scenario_ids: set[str]) -> dict[str, dict[tuple[str, str], PowerOptionReview]]:
    if not scenario_ids:
        return {}
    out: dict[str, dict[tuple[str, str], PowerOptionReview]] = {}
    for r in db.query(PowerOptionReview).filter(PowerOptionReview.scenario_ref.in_(scenario_ids)).all():
        out.setdefault(r.scenario_ref, {})[(r.variant_ref, r.option_key)] = r
    return out


_STATUS_RANK = {"rejected": 0, "candidate": 1, "iq_eval": 2, "adopted": 3}


def item_status(reviews: dict[tuple[str, str], PowerOptionReview], variant_id: str, key: str) -> dict[str, Any]:
    r = reviews.get((variant_id, key)) or reviews.get(("*", key))
    if r is None:
        return {"status": "candidate", "scope": None, "note": None}
    return {"status": r.status, "scope": "variant" if r.variant_ref != "*" else "scenario", "note": r.note,
            "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def set_status(item_states: list[dict[str, Any]]) -> str:
    """A set is only as far as its least-advanced item; one rejected item rejects the set."""
    if not item_states:
        return "candidate"
    return min((s["status"] for s in item_states), key=lambda s: _STATUS_RANK.get(s, 1))


def board_options(po: dict[str, Any] | None, reviews: dict[tuple[str, str], PowerOptionReview],
                  variant_id: str) -> dict[str, Any]:
    if po is None:
        return {"status": "not_explored", "results": [], "items": [], "notes": [
            "prediction registered before power-option exploration; re-run exploration and promote"]}
    items = {i["key"]: i for d in po.get("dimensions") or [] for i in d.get("items") or []}
    states = {k: item_status(reviews, variant_id, k) for k in items}
    results = []
    for r in po.get("results") or []:
        st = set_status([states[k] for k in r["items"] if k in states])
        results.append({k: r.get(k) for k in ("key", "items", "labels", "kinds", "iq_eval", "spec_ok", "spec_reasons",
                                              "total_mw", "delta_mw", "delta_pct", "delta_bw_mbs", "raw_delta_mw",
                                              "raw_delta_pct", "attribution", "fill_pct")} | {"review_status": st})
    live = [r for r in results if r["spec_ok"] and r["review_status"] != "rejected" and (r["delta_mw"] or 0) < 0]
    best = min(live, key=lambda r: r["delta_mw"], default=None)
    return {
        "status": po.get("status"), "notes": po.get("notes") or [], "sets": po.get("sets"),
        "reference": po.get("reference"),
        "items": [items[k] | {"review": states[k]} for k in items],
        "results": results,
        "best": ({"key": best["key"], "labels": best["labels"], "delta_mw": best["delta_mw"],
                  "delta_pct": best["delta_pct"], "review_status": best["review_status"]} if best else None),
    }


def list_option_reviews(db: Session, *, project_ref: str | None = None,
                        scenario_id: str | None = None) -> list[dict[str, Any]]:
    q = db.query(PowerOptionReview)
    if project_ref:
        q = q.filter(PowerOptionReview.project_ref == project_ref)
    if scenario_id:
        q = q.filter(PowerOptionReview.scenario_ref == scenario_id)
    return [_review_dict(r) for r in q.order_by(PowerOptionReview.scenario_ref, PowerOptionReview.option_key,
                                                 PowerOptionReview.variant_ref).all()]


def _review_dict(r: PowerOptionReview) -> dict[str, Any]:
    return {"id": r.id, "project_ref": r.project_ref, "scenario_id": r.scenario_ref, "variant_id": r.variant_ref,
            "option_key": r.option_key, "status": r.status, "note": r.note, "history": r.history,
            "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def set_option_review(db: Session, request: PowerOptionReviewRequest, user: str | None = None) -> dict[str, Any]:
    # Lock an existing parent even when this review has not been created yet.
    scenario = db.query(Scenario).filter_by(id=request.scenario_id).with_for_update().one_or_none()
    if scenario is None:
        raise NotFoundError(f"scenario not found: {request.scenario_id}")
    if request.variant_id != "*" and db.query(ScenarioVariant).filter_by(
            scenario_id=request.scenario_id, id=request.variant_id).one_or_none() is None:
        raise NotFoundError(f"variant not found: {request.scenario_id}/{request.variant_id}")
    row = (db.query(PowerOptionReview)
           .filter_by(scenario_ref=request.scenario_id, variant_ref=request.variant_id, option_key=request.option_key)
           .with_for_update().one_or_none())
    now = _now()
    entry = {"status": request.status, "note": request.note, "by": user, "at": now.isoformat()}
    if row is None:
        row = PowerOptionReview(
            id=f"POR-{uuid4().hex}", project_ref=scenario.project_ref, scenario_ref=request.scenario_id,
            variant_ref=request.variant_id, option_key=request.option_key, history=[entry],
        )
        db.add(row)
    else:
        row.history = [*(row.history or []), entry]
    row.status, row.note, row.updated_by, row.updated_at = request.status, request.note, user, now
    db.commit()
    return _review_dict(row)


# ------------------------------------------------------------------- model status
def _is_sample(ref: str | None) -> bool:
    return bool(ref) and any(k in str(ref).lower() for k in ("sample", "synthetic"))


def model_status(db: Session, *, project_ref: str | None = None) -> dict[str, Any]:
    """What the displayed numbers rest on: engine rev, DVFS tables, real vs synthetic measurements.

    ``stale_engine`` counts current predictions registered by a run of an older exploration
    engine — their numbers are not what the current code would produce.
    """
    q = db.query(Prediction).filter(Prediction.status == "current")
    if project_ref:
        q = q.filter(Prediction.project_ref == project_ref)
    preds = q.all()
    run_ids = {p.exploration_run_ref for p in preds}
    runs = {r.id: r for r in db.query(ArchExplorationRun).filter(ArchExplorationRun.id.in_(run_ids)).all()} if run_ids else {}
    engines: dict[str, int] = {}
    dvfs: dict[str, int] = {}
    for p in preds:
        run = runs.get(p.exploration_run_ref)
        rev = run.engine_rev if run is not None else "unknown"
        engines[rev] = engines.get(rev, 0) + 1
        ref = p.dvfs_table_ref or (run.dvfs_table_ref if run is not None else None)
        if ref:
            dvfs[ref] = dvfs.get(ref, 0) + 1

    mq = db.query(Evidence.provenance).filter(Evidence.kind == "evidence.measurement")
    if project_ref:
        scenario_ids = [sid for (sid,) in db.query(Scenario.id).filter(Scenario.project_ref == project_ref).all()]
        mq = mq.filter(Evidence.scenario_ref.in_(scenario_ids)) if scenario_ids else mq.filter(Evidence.id.is_(None))
    real = synthetic = 0
    for (prov,) in mq.all():
        if is_synthetic(prov):
            synthetic += 1
        else:
            real += 1

    rq = db.query(ArchExplorationRun)
    if project_ref:
        rq = rq.filter(ArchExplorationRun.project_ref == project_ref)
    latest = rq.order_by(ArchExplorationRun.created_at.desc()).first()
    lineage = run_lineage({"variants": latest.variants, "summary": latest.summary})[0] if latest is not None else None
    return {
        "engine_rev": ENGINE_REV,
        "project_ref": project_ref,
        "predictions": {"current": len(preds), "stale_engine": sum(n for e, n in engines.items() if e != ENGINE_REV),
                        "engines": engines},
        "dvfs": [{"ref": ref, "sample": _is_sample(ref), "predictions": n} for ref, n in sorted(dvfs.items())],
        "measurements": {"real": real, "synthetic": synthetic},
        "lineage": lineage,
        "latest_run": {"id": latest.id, "engine_rev": latest.engine_rev,
                       "created_at": latest.created_at.isoformat() if latest.created_at else None} if latest is not None else None,
    }
