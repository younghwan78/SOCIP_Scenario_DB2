"""Architecture exploration runs -> predictions (current/superseded) -> review reports."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, literal, literal_column, text, tuple_
from sqlalchemy.orm import Session, defer, load_only

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
from scenario_db.reporting.report_package import package_zip
from scenario_db.reporting.xlsx_export import report_sheets, write_xlsx
from scenario_db.sim.arch_exploration import ENGINE_REV, explore_variant, find_case, prediction_payload
from scenario_db.sim.power_attribution import attribute
from scenario_db.api.services.calibration import data_origin, is_physical, is_synthetic, measurement_details
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
def _reference_budgets(db: Session, project_ref: str | None) -> dict[str, dict[str, Any]]:
    """variant id -> {"mw": reference x (1 + tol), "reference_mw", "source"} from the project review_policy."""
    if not project_ref:
        return {}
    from scenario_db.api.services.review import power_references

    refs = power_references(db, project_ref)
    tol = (refs.get("tolerance_pct") or 0.0) / 100.0
    return {vid: {"mw": round(r["mw"] * (1 + tol), 2), "reference_mw": r["mw"], "source": r["source"]}
            for vid, r in refs["references"].items() if r.get("mw")}


def _variant_budget(spec_mw: float | None, ref: dict[str, Any] | None) -> dict[str, Any]:
    if ref is None:
        return {"mw": spec_mw, "source": "spec" if spec_mw is not None else None}
    if spec_mw is not None and spec_mw <= ref["mw"]:
        return {"mw": spec_mw, "source": "spec", "reference_mw": ref["reference_mw"]}
    return {"mw": ref["mw"], "source": f"전과제 {ref['source']}", "reference_mw": ref["reference_mw"]}


def run_exploration(db: Session, request: ArchExplorationRunRequest, user: str | None = None) -> dict[str, Any]:
    scenarios = _scenarios(db, request)
    throughput_from_policy = "throughput_model" not in request.spec.timing.model_fields_set
    # project review policy decides the throughput judgement unless the spec sets it (stored in run.spec)
    from scenario_db.api.services.review_policy import apply_throughput, project_policy

    timing = apply_throughput(request.spec.timing, project_policy(db, scenarios[0].project_ref))
    if timing is not request.spec.timing:
        request = request.model_copy(update={"spec": request.spec.model_copy(update={"timing": timing})})
    plan = [(s, v) for s in scenarios for v in _variant_ids(db, s.id, request)]
    if not plan:
        raise NotFoundError("exploration scope has no variants")
    if len(plan) > request.max_variants:
        raise UnprocessableError(f"exploration scope has {len(plan)} variants > max_variants {request.max_variants}")
    variants: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    blobs: dict[str, Any] = {}
    soc_ref = request.soc_ref
    dvfs_ref: str | None = None
    remaining_cases = 2_000_000
    ref_budget = _reference_budgets(db, scenarios[0].project_ref) if request.power_budget_from_reference else {}
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
            from scenario_db.api.services.cpu import with_cpu_profile

            bounded_spec = request.spec.model_copy(update={
                "max_cases_per_variant": min(request.spec.max_cases_per_variant, remaining_cases),
                "timing": with_cpu_profile(db, request.spec.timing, scenario.id, variant_id),
            })
            budget = _variant_budget(request.spec.constraints.power_budget_mw, ref_budget.get(variant_id))
            if budget["mw"] != request.spec.constraints.power_budget_mw:
                bounded_spec = bounded_spec.model_copy(update={
                    "constraints": bounded_spec.constraints.model_copy(update={"power_budget_mw": budget["mw"]})})
            _check_power_params_scope(shim.config, graph)
            stage = "explore"
            summary = explore_variant(graph, bounded_spec, config=shim.config, dvfs_tables=tables)
            summary["model_lineage"] = run_model_lineage(shim.config)
            if budget["mw"] is not None:
                summary["power_budget"] = budget
        except Exception as exc:  # noqa: BLE001 - one variant must not abort the run
            errors.append(variant_failure(exc, variant_id=variant_id, scenario_id=scenario.id, stage=stage))
            continue
        soc_ref = soc_ref or _graph_soc_ref(graph)
        dvfs_ref = dvfs_ref or ref
        remaining_cases -= summary["counts"]["cases"] + summary["counts"].get("option_cases", 0)
        summary["dvfs_table_ref"] = ref
        blobs.update(summary.pop("_manifest_blobs", {}) or {})
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
        spec=request.spec.model_dump(mode="json") | {"scenario_ids": [s.id for s in scenarios], "category": request.category,
                                                      "config_profile_ref": request.config_profile_ref,
                                                      "input_selection": request.model_dump(mode="json", include={
                                                          "config", "config_profile_ref", "dvfs_tables", "dvfs_table_ref",
                                                          "soc_ref", "dvfs_version", "use_default_dvfs"}, exclude_unset=True),
                                                      "throughput_from_policy": throughput_from_policy,
                                                      **({"timing_budget": request.timing_budget} if request.timing_budget else {}),
                                                      # resolved inputs, content-addressed (variants[].input_sections -> blobs)
                                                      "manifest": {"engine_rev": ENGINE_REV, "tool_version": _tool_version(),
                                                                   "blobs": blobs}},
        variants=variants, errors=errors, summary=counts, dvfs_table_ref=dvfs_ref,
        engine_rev=ENGINE_REV, input_hash=ihash, created_by=user, created_at=_now(),
    )
    db.add(row)
    db.commit()
    return run_detail(row)


def _tool_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("02-scenariodb")
    except Exception:  # noqa: BLE001 - not installed as a distribution
        return None


def run_manifest(db: Session, run_id: str) -> dict[str, Any]:
    """Resolved inputs of every variant of a run (re-creates a past exploration)."""
    row = get_run(db, run_id)
    m = (row.spec or {}).get("manifest") or {}
    blobs = m.get("blobs") or {}
    return {"run_id": row.id, "engine_rev": m.get("engine_rev") or row.engine_rev, "tool_version": m.get("tool_version"),
            "available": bool(blobs),
            "variants": [{"scenario_id": v["scenario_id"], "variant_id": v["variant_id"], "input_hash": v.get("input_hash"),
                          "sections": v.get("input_sections") or {}} for v in row.variants or []],
            "blobs": blobs}


def _run_meta(row: ArchExplorationRun) -> dict[str, Any]:
    return {
        "id": row.id, "title": row.title, "scenario_type": row.scenario_type, "project_ref": row.project_ref,
        "soc_ref": row.soc_ref, "dvfs_table_ref": row.dvfs_table_ref, "engine_rev": row.engine_rev,
        "config_profile_ref": (row.spec or {}).get("config_profile_ref"),
        "summary": row.summary, "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


SUMMARY_KEYS = ("scenario_id", "variant_id", "design_conditions", "severity", "fps", "period_ms", "eis_on", "mfc_dual",
                "spec_ok", "spec_reasons", "status", "objective", "counts", "distribution", "baseline", "recommended",
                "coverage", "dvfs_table_ref", "input_hash", "model_lineage", "keep_total_mw", "throughput_model",
                "power_budget")
SW_MARGIN_SUMMARY_KEYS = ("worst", "growth_tolerance", "growth_tolerance_fixed", "growth_tested_max", "recommendations",
                          "verdict", "stat_spread_ms")


def variant_summary(v: dict[str, Any]) -> dict[str, Any]:
    """List view of one explored variant (~2 KB instead of ~70 KB): what the run table, range and composition
    charts and bulk promotion read. Slices, buffers, DVFS domains, IP modes, Pareto and option results stay
    in the variant detail endpoint."""
    out = {k: v.get(k) for k in SUMMARY_KEYS if k in v}
    out["sw_margin"] = {k: (v.get("sw_margin") or {}).get(k) for k in SW_MARGIN_SUMMARY_KEYS} | {"stages": []}
    po = v.get("power_options")
    out["power_options"] = None
    if po:
        best = [r for r in po.get("results") or [] if r.get("key") == po.get("best")]
        out["power_options"] = {"status": po.get("status"), "best": po.get("best"), "sets": po.get("sets"),
                                "notes": po.get("notes") or [], "results": best, "dimensions": [], "errors": []}
    out["alternatives"] = []
    out["detail"] = False  # the UI fetches the full summary on selection
    return out


def run_detail(row: ArchExplorationRun, view: str = "full") -> dict[str, Any]:
    spec = {k: v for k, v in (row.spec or {}).items() if k != "manifest"}  # blobs via /manifest only
    spec["manifest_available"] = bool(((row.spec or {}).get("manifest") or {}).get("blobs"))
    variants = row.variants if view == "full" else [variant_summary(v) for v in row.variants or []]
    return _run_meta(row) | {"spec": spec, "variants": variants, "errors": row.errors, "view": view}


_SUMMARY_SQL = text("""
SELECT coalesce(jsonb_agg(
         coalesce((SELECT jsonb_object_agg(k, e->k) FROM unnest(ARRAY[%(keys)s]) k WHERE e ? k), '{}'::jsonb)
         || jsonb_build_object(
              'sw_margin', jsonb_build_object(%(sw)s, 'stages', '[]'::jsonb),
              'power_options', CASE WHEN coalesce(e->'power_options', 'null'::jsonb) IN ('null'::jsonb, '{}'::jsonb) THEN NULL
                ELSE jsonb_build_object(
                  'status', e->'power_options'->'status', 'best', e->'power_options'->'best',
                  'sets', e->'power_options'->'sets', 'notes', coalesce(e->'power_options'->'notes', '[]'::jsonb),
                  'dimensions', '[]'::jsonb, 'errors', '[]'::jsonb,
                  'results', coalesce((SELECT jsonb_agg(r) FROM jsonb_array_elements(
                      coalesce(e->'power_options'->'results', '[]'::jsonb)) r
                    WHERE r->>'key' = e->'power_options'->>'best'), '[]'::jsonb)) END,
              'alternatives', '[]'::jsonb, 'detail', false)
         ORDER BY ord), '[]'::jsonb)
FROM arch_exploration_runs, jsonb_array_elements(variants) WITH ORDINALITY AS t(e, ord)
WHERE id = :run_id
""" % {"keys": ", ".join(f"'{k}'" for k in SUMMARY_KEYS),
       "sw": ", ".join(f"'{k}', e->'sw_margin'->'{k}'" for k in SW_MARGIN_SUMMARY_KEYS)})


def run_summary(db: Session, run_id: str) -> dict[str, Any]:
    """``run_detail(view="summary")`` with the per-variant trimming done in PostgreSQL: the ~70 KB per-variant
    summaries are never parsed in Python (same rows as ``variant_summary``)."""
    R = ArchExplorationRun
    row = (db.query(R).options(defer(R.variants), defer(R.spec))
           .filter(R.id == run_id).one_or_none())
    if row is None:
        raise NotFoundError(f"exploration run not found: {run_id}")
    spec, has_blobs = db.query(R.spec.op("-")("manifest"), R.spec["manifest"]["blobs"].isnot(None)).filter(R.id == run_id).one()
    variants = db.execute(_SUMMARY_SQL, {"run_id": run_id}).scalar() or []
    meta = {"id": row.id, "title": row.title, "scenario_type": row.scenario_type, "project_ref": row.project_ref,
            "soc_ref": row.soc_ref, "dvfs_table_ref": row.dvfs_table_ref, "engine_rev": row.engine_rev,
            "config_profile_ref": (spec or {}).get("config_profile_ref"), "summary": row.summary,
            "created_by": row.created_by, "created_at": row.created_at.isoformat() if row.created_at else None}
    return meta | {"spec": (spec or {}) | {"manifest_available": bool(has_blobs)}, "variants": variants,
                   "errors": row.errors, "view": "summary"}


def run_variant(db: Session, run_id: str, scenario_id: str, variant_id: str) -> dict[str, Any]:
    """One variant's full exploration summary, extracted in SQL (the other variants are not transferred)."""
    R = ArchExplorationRun
    found = db.query(R.id, func.jsonb_path_query_first(
        R.variants, literal_column("'$[*] ? (@.scenario_id == $s && @.variant_id == $v)'::jsonpath"),
        func.jsonb_build_object(literal("s"), scenario_id, literal("v"), variant_id))).filter(R.id == run_id).one_or_none()
    if found is None:
        raise NotFoundError(f"exploration run not found: {run_id}")
    if found[1] is None:
        raise NotFoundError(f"variant {scenario_id}/{variant_id} not in run {run_id}")
    return found[1] | {"detail": True}


def list_runs(db: Session, *, scenario_type: str | None = None, project_ref: str | None = None,
              limit: int = 50) -> list[dict[str, Any]]:
    R = ArchExplorationRun
    # meta columns only: variants / spec (with the input manifest) are megabytes per run
    q = db.query(R.id, R.title, R.scenario_type, R.project_ref, R.soc_ref, R.dvfs_table_ref, R.engine_rev, R.summary,
                 R.created_by, R.created_at, R.spec["config_profile_ref"].astext)
    if scenario_type:
        q = q.filter(R.scenario_type == scenario_type)
    if project_ref:
        q = q.filter(R.project_ref == project_ref)
    return [{"id": r[0], "title": r[1], "scenario_type": r[2], "project_ref": r[3], "soc_ref": r[4], "dvfs_table_ref": r[5],
             "engine_rev": r[6], "config_profile_ref": r[10], "summary": r[7], "created_by": r[8],
             "created_at": r[9].isoformat() if r[9] else None}
            for r in q.order_by(R.created_at.desc()).limit(limit).all()]


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


def promote(db: Session, request: PromoteRequest, user: str | None = None, *, rule: str | None = None) -> dict[str, Any]:
    """``rule`` (internal callers only): selection rule recorded instead of the default, e.g. ``manual:timing-budget``."""
    run = get_run(db, request.run_id)
    if request.expected_project_ref is not None and run.project_ref != request.expected_project_ref:
        raise UnprocessableError(
            f"run {run.id} belongs to project {run.project_ref!r}, not the selected {request.expected_project_ref!r}; "
            "predictions are only registered for the run's own project")
    summaries = [v for v in run.variants if request.scenario_id is None or v["scenario_id"] == request.scenario_id]
    if request.variant_ids is not None and request.scenario_id is None:
        for vid in request.variant_ids:
            if sum(v["variant_id"] == vid for v in summaries) > 1:
                raise UnprocessableError("ambiguous variant_id; specify scenario_id")
    targets = [v for v in summaries if (v["variant_id"] in request.variant_ids
               if request.variant_ids is not None else v["spec_ok"])]
    # Lock the stable variant row, including the first promotion when no prediction exists.
    # Acquire all locks in canonical order to avoid deadlocks between overlapping requests.
    # One statement: rows are locked in the ORDER BY order, the same canonical order as before.
    keys = sorted({(v["scenario_id"], v["variant_id"]) for v in targets})
    if keys:
        locked = (db.query(ScenarioVariant.scenario_id, ScenarioVariant.id)
                  .filter(tuple_(ScenarioVariant.scenario_id, ScenarioVariant.id).in_(keys))
                  .order_by(ScenarioVariant.scenario_id, ScenarioVariant.id).with_for_update().all())
        if len(locked) != len(keys):
            raise UnprocessableError("explored variant no longer exists")
    currents = {(p.scenario_ref, p.variant_ref): p for p in db.query(Prediction)
                .options(load_only(Prediction.id, Prediction.scenario_ref, Prediction.variant_ref, Prediction.status))
                .filter(Prediction.status == "current",
                        tuple_(Prediction.scenario_ref, Prediction.variant_ref).in_(keys)).all()} if keys else {}
    promoted, skipped = [], []
    new_rows: list[tuple[Prediction, float]] = []
    # review policy: the default registration may be the IQ/performance-keeping optimum (no lossy / assumed ratio)
    from scenario_db.api.services.review_policy import project_policy

    policy = project_policy(db, run.project_ref)
    iq_keep = policy is not None and policy.register_baseline == "iq_keep" and rule is None
    rule_override = rule
    for vid in dict.fromkeys(request.variant_ids or []):
        if not any(v["variant_id"] == vid for v in targets):
            skipped.append({"variant_id": vid, "reason": "variant not in run"})
    for summary in targets:
        vid = summary["variant_id"]
        constraints = (run.spec or {}).get("constraints") or {}
        if ((summary.get("status") or {}).get("power_budget_status") == "unknown"
                and constraints.get("require_complete_power_for_budget", True)):
            raise UnprocessableError("power budget cannot be verified with an incomplete power model")
        keep = ((summary.get("tiers") or {}).get("keep") or {}).get("best")
        if request.case_key is None and iq_keep:
            case, rule = keep, "auto:min-power-iq"
        else:
            case, rule = find_case(summary, request.case_key)
        rule = rule_override or rule
        if case is None:
            skipped.append({"variant_id": vid, "reason": "no eligible case" if request.case_key is None else "case_key not found"})
            continue
        if not rule.startswith("auto:") and not request.reason:
            raise UnprocessableError("a non-default case needs a reason")
        if not rule.startswith("auto:") and not case.get("eligible", True):
            raise UnprocessableError("selected case is not eligible (spec)")
        if case.get("verified") and not case["verified"]["ok"]:
            raise UnprocessableError("selected case failed re-simulation verification")
        metrics = prediction_payload(summary["objective_slice"], case, summary["buffers"])
        metrics |= {"dvfs_table_ref": summary.get("dvfs_table_ref"), "exploration_run_ref": run.id,
                    "design_conditions": summary.get("design_conditions"),
                    "distribution": summary["distribution"], "alternatives": len(summary.get("alternatives") or []),
                    "eligible_cases": summary["counts"]["eligible"], "verified": case.get("verified"),
                    "power_options": option_snapshot(summary.get("power_options"), case, rule),
                    "model_lineage": summary.get("model_lineage"),
                    # None = registered before the review policy (stage judgement)
                    "throughput_model": summary.get("throughput_model")}
        prev = currents.get((summary["scenario_id"], vid))
        pred = Prediction(
            id=f"PRED-{uuid4().hex}",
            scenario_ref=summary["scenario_id"], variant_ref=vid, project_ref=run.project_ref,
            status="current", exploration_run_ref=run.id, case_key=case["key"], selection_rule=rule,
            selected_by="auto" if rule.startswith("auto:") else "user", selected_by_user=user,
            reason=request.reason, metrics=metrics, input_hash=summary["input_hash"],
            dvfs_table_ref=summary.get("dvfs_table_ref"), supersedes_ref=prev.id if prev else None,
            created_at=_now(),
        )
        new_rows.append((pred, metrics["power"]["total_mw"]))
    # supersede first (one current per variant), then insert the new predictions in one flush
    replaced = [pred.supersedes_ref for pred, _ in new_rows if pred.supersedes_ref]
    if replaced:
        db.query(Prediction).filter(Prediction.id.in_(replaced)).update({"status": "superseded"}, synchronize_session=False)
        db.flush()
    db.add_all([pred for pred, _ in new_rows])
    db.flush()
    promoted = [_pred_dict(pred, metrics=False) | {"total_mw": total} for pred, total in new_rows]
    db.commit()
    return {"run_id": run.id, "promoted": promoted, "skipped": skipped}


BOARD_METRIC_KEYS = ("fps", "power", "bw_mbs", "distribution", "compression", "dvfs", "verdict", "eligible_cases",
                     "alternatives", "verified", "statistic", "runtime_scale", "model_lineage", "power_options",
                     "verdict_detail", "stages", "intervals", "intervals_ok", "period_ms", "latency", "throughput_model")

STAGE_KEYS = ("id", "name", "sw_ms", "hw_ms", "budget_ms", "overhead_ms", "margin", "feasible", "fill_pct",
              "throughput", "longest_sw_ms", "chain_ms")


def verdict_detail(m: dict[str, Any]) -> dict[str, Any] | None:
    """Why a registered prediction got its timing verdict: stored reasons (predictions promoted after
    verdict_detail existed) or reasons re-derived from the frozen stages / intervals (older ones)."""
    status = m.get("verdict")
    if not status:
        return None
    raw = m.get("stages") or {}
    stages = [({"id": key} | {k: st.get(k) for k in STAGE_KEYS if k in st}) for key, st in (raw.items() if isinstance(raw, dict) else
              ((st.get("id"), st) for st in raw))]
    period = m.get("period_ms")
    iv = m.get("intervals") or {}
    intervals = {k: iv.get(k) for k in ("preview", "video") if isinstance(iv.get(k), (int, float))}
    stored = m.get("verdict_detail")
    if stored:
        reasons, factor, derived = list(stored.get("reasons") or []), stored.get("nrt_clock_factor"), False
    else:
        reasons, factor, derived = [], None, True
        for st in stages:
            if st.get("feasible") is False:
                reasons.append(f"{st.get('name') or st['id']}: SW {float(st.get('sw_ms') or 0):.2f} ms leaves no HW budget")
            elif st.get("id") == "rt" and st.get("hw_ms") is not None and st.get("budget_ms") is not None \
                    and float(st["hw_ms"]) > float(st["budget_ms"]) * 1.0001:
                reasons.append(f"RT HW {float(st['hw_ms']):.2f} ms > budget {float(st['budget_ms']):.2f} ms")
        if m.get("intervals_ok") is False and period:
            for k, v in intervals.items():
                reasons.append(f"{k} interval {v:.3f} ms vs {float(period):.3f} ms")
        if status == "clock_up":
            full = [st for st in stages if st.get("id") == "nrt" and float(st.get("fill_pct") or 0) >= 99.0]
            reasons.append("NRT HW가 budget을 꽉 채움 (점유 ≥ 99%) — NRT clock을 25% rule보다 올려서 맞춘 상태"
                           if full else "NRT clock을 25% rule보다 올려야 budget을 맞춤")
            reasons.append("clock 배율은 이 예측에 저장되지 않음 — 다시 등록하면 표시됩니다")
        if status == "fail" and not reasons:
            reasons.append("timing fail (detail not stored for this prediction)")
    return {"status": status, "reasons": reasons, "nrt_clock_factor": factor, "derived": derived,
            "stages": stages, "intervals": intervals, "period_ms": period, "latency": m.get("latency"),
            "statistic": m.get("statistic"), "runtime_scale": m.get("runtime_scale")}


def _metrics_subset(keys: tuple[str, ...]) -> Any:
    """Selected top-level keys of ``predictions.metrics`` built in SQL (the IP / buffer / stage rows stay in the DB)."""
    return func.jsonb_build_object(*[x for k in keys for x in (literal(k), Prediction.metrics[k])])


def board(db: Session, *, scenario_id: str | None = None, project_ref: str | None = None) -> dict[str, Any]:
    q = db.query(Prediction, _metrics_subset(BOARD_METRIC_KEYS)).options(defer(Prediction.metrics)) \
        .filter(Prediction.status == "current")
    if scenario_id:
        q = q.filter(Prediction.scenario_ref == scenario_id)
    if project_ref:
        q = q.filter(Prediction.project_ref == project_ref)
    current = q.order_by(Prediction.scenario_ref, Prediction.variant_ref).all()
    prev_ids = [p.supersedes_ref for p, _ in current if p.supersedes_ref]
    prev = {pid: m for pid, m in db.query(Prediction.id, _metrics_subset(("power", "model_lineage")))
            .filter(Prediction.id.in_(prev_ids)).all()} if prev_ids else {}
    runs = {r.id: r for r in db.query(ArchExplorationRun.id, ArchExplorationRun.title, ArchExplorationRun.created_at,
                                       ArchExplorationRun.scenario_type,
                                       ArchExplorationRun.spec["timing"].label("timing"),
                                       ArchExplorationRun.spec["axes"].label("axes"),
                                       ArchExplorationRun.spec["config_profile_ref"].label("profile"),
                                       ArchExplorationRun.spec["input_selection"].label("selection"),
                                       ArchExplorationRun.spec["timing_budget"].label("tb"))
            .filter(ArchExplorationRun.id.in_({p.exploration_run_ref for p, _ in current})).all()} if current else {}
    reviews = _reviews_by_scenario(db, {p.scenario_ref for p, _ in current})
    rows = []
    for p, m in current:
        old_m = prev.get(p.supersedes_ref) if p.supersedes_ref else None
        old = {"id": p.supersedes_ref, "metrics": old_m} if old_m is not None else None
        run = runs.get(p.exploration_run_ref)
        rows.append(_pred_dict(p, metrics=False) | {
            "run_title": run.title if run else None, "run_created_at": run.created_at.isoformat() if run and run.created_at else None,
            "fps": m.get("fps"), "power": m["power"], "bw_mbs": m.get("bw_mbs"), "distribution": m.get("distribution"),
            "compression": m.get("compression"), "dvfs": m.get("dvfs"), "verdict": m.get("verdict"),
            "eligible_cases": m.get("eligible_cases"), "alternatives": m.get("alternatives"), "verified": m.get("verified"),
            "statistic": m.get("statistic"), "runtime_scale": m.get("runtime_scale"),
            "previous": ({"id": old["id"], "total_mw": old["metrics"]["power"]["total_mw"],
                          "delta_mw": round(m["power"]["total_mw"] - old["metrics"]["power"]["total_mw"], 3),
                          "lineage_changes": lineage_differences(old["metrics"].get("model_lineage"),
                                                                 m.get("model_lineage"))} if old else None),
            "power_options": board_options(m.get("power_options"), reviews.get(p.scenario_ref, {}), p.variant_ref),
            "verdict_detail": verdict_detail(m),
            "throughput_model": m.get("throughput_model") or "stage",
            "condition": _condition(run, m),
        })
    return {"rows": rows, "review_statuses": list(POWER_OPTION_STATUSES)}


def _condition(run, m: dict[str, Any]) -> dict[str, Any]:
    """The analysis condition a prediction was registered with (to re-open it in Timing Budget)."""
    timing = (getattr(run, "timing", None) or {}) if run is not None else {}
    axes = (getattr(run, "axes", None) or {}) if run is not None else {}
    sel = (getattr(run, "selection", None) or {}) if run is not None else {}
    return {
        "source": "timing-budget" if run is not None and getattr(run, "scenario_type", None) == "timing-budget" else "exploration",
        "statistic": m.get("statistic"), "runtime_scale": m.get("runtime_scale"),
        "throughput_model": m.get("throughput_model") or "stage", "eis": axes.get("eis") or "auto",
        "cpu_model": timing.get("cpu_model") or "flat",
        "rt_margin": timing.get("rt_margin"), "output_margin": timing.get("output_margin"),
        "warmup_frames": timing.get("warmup_frames") or 0,
        "config_profile_ref": sel.get("config_profile_ref") or (getattr(run, "profile", None) if run is not None else None),
        "dvfs_overrides": ((sel.get("config") or {}).get("dvfs_overrides") or {}),
        "dvfs": m.get("dvfs") or {}, "compression": m.get("compression") or [],
        # S4: measurement used as input (SW task runtime / IP clocks / CPU profile)
        "measured": {"ref": ((getattr(run, "tb", None) or {}).get("measured") or {}).get("measurement_ref") if run is not None else None,
                     "inputs": ((getattr(run, "tb", None) or {}).get("measured") or {}) if run is not None else {},
                     "sw": sorted((timing.get("task_runtime") or {}).keys()),
                     "clock_ref": (sel.get("config") or {}).get("measured_clock_ref"),
                     "cpu_ref": timing.get("cpu_profile_ref") if timing.get("cpu_model") == "profile" else None},
    }


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
    if request.status != "draft":
        raise UnprocessableError("reports must be created as draft; publishing requires a review")
    run = get_run(db, request.run_id)
    vids = [(v["scenario_id"], v["variant_id"]) for v in run.variants]
    preds: dict[tuple[str, str], dict[str, Any]] = {}
    changes: dict[tuple[str, str], dict[str, Any]] = {}
    # one query for the run's current predictions (+ one for what they superseded), not 2 per variant
    wanted = set(vids)
    currents = [p for p in db.query(Prediction).filter(
        Prediction.status == "current", Prediction.exploration_run_ref == run.id,
        Prediction.scenario_ref.in_({sid for sid, _ in vids})).all() if (p.scenario_ref, p.variant_ref) in wanted]
    olds = {p.id: p for p in db.query(Prediction).filter(
        Prediction.id.in_([c.supersedes_ref for c in currents if c.supersedes_ref])).all()} if currents else {}
    order = {k: i for i, k in enumerate(vids)}
    for cur in sorted(currents, key=lambda p: order[(p.scenario_ref, p.variant_ref)]):  # this run's predictions only
        key = (cur.scenario_ref, cur.variant_ref)
        preds[key] = _pred_dict(cur)
        old = olds.get(cur.supersedes_ref) if cur.supersedes_ref else None
        if old is not None:
            changes[key] = attribute(old.metrics, cur.metrics)
    run_dict = run_detail(run) | {"created_at": run.created_at}
    snapshot = build_snapshot(run_dict, preds, changes, _report_calibration(db, preds))
    clock = _report_clock(db, preds)
    if clock:
        snapshot["clock_residency"] = clock  # absent key = report generated before clock residency existed
    from scenario_db.api.services.review import report_context

    blobs = ((run.spec or {}).get("manifest") or {}).get("blobs") or {}
    config_hash = ((run.variants[0] if run.variants else {}).get("input_sections") or {}).get("config")
    snapshot["review_context"] = report_context(db, run.project_ref, (run.spec or {}).get("config_profile_ref"), preds,
                                                 frozen_config=blobs.get(config_hash))
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


def _has_total(m: Evidence) -> bool:
    t = (m.kpi or {}).get("total_power_mw")
    return (t.get("mean") if isinstance(t, dict) else t) is not None


def _meas_rank(m: Evidence) -> int:
    """Comparable capture first (has total power), then real silicon over synthetic; ties keep the newest."""
    return 4 * _has_total(m) + 2 * is_physical(m.provenance) + (not is_synthetic(m.provenance))


def _report_calibration(db: Session, preds: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest measurement per reported variant (real silicon preferred over synthetic) vs its registered prediction."""
    if not preds:
        return []
    keys = set(preds)
    found: dict[tuple[str, str], Evidence] = {}
    rows = (db.query(Evidence).options(load_only(Evidence.id, Evidence.scenario_ref, Evidence.variant_ref,
                                                 Evidence.measured_at, Evidence.provenance, Evidence.kpi))
            .filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref.in_({sid for sid, _ in keys}))
            .order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all())
    for m in rows:
        key = (m.scenario_ref, m.variant_ref)
        if key not in keys:
            continue
        held = found.get(key)
        if held is None or _meas_rank(m) > _meas_rank(held):
            found[key] = m
    details = measurement_details(db, [m.id for m in found.values()])  # constant query count
    out = []
    for (sid, vid), m in sorted(found.items()):
        row = calibration_row(vid, sid, details[m.id], preds[(sid, vid)]["id"])
        if row is not None:
            out.append(row)
    return out


def _report_clock(db: Session, preds: dict[tuple[str, str], dict[str, Any]]) -> list[dict[str, Any]]:
    """Per reported variant, the newest measurement with clock residency (real silicon preferred)."""
    from scenario_db.api.services.calibration import clock_residency_of
    from scenario_db.db.models.capability import PowerModelParams
    from scenario_db.reporting.clock_section import report_rows

    if not preds:
        return []
    keys = set(preds)
    rows = (db.query(Evidence).options(load_only(Evidence.id, Evidence.scenario_ref, Evidence.variant_ref, Evidence.measured_at,
                                                 Evidence.provenance, Evidence.metric_observations, Evidence.cpu_breakdown, Evidence.vdd_power))
            .filter(Evidence.kind == "evidence.measurement", Evidence.scenario_ref.in_({sid for sid, _ in keys}))
            .order_by(Evidence.measured_at.desc().nullslast(), Evidence.id).all())
    from scenario_db.db.models.capability import IpCatalog

    params_rows = db.query(PowerModelParams).all()
    ip_rows = db.query(IpCatalog).options(load_only(IpCatalog.id, IpCatalog.capabilities, IpCatalog.compatible_soc)).all()
    found: dict[tuple[str, str], tuple[Evidence, dict[str, Any]]] = {}
    for m in rows:
        key = (m.scenario_ref, m.variant_ref)
        if key not in keys:
            continue
        held = found.get(key)
        if held is not None and not (is_physical(m.provenance) and not is_physical(held[0].provenance)):
            continue
        view = clock_residency_of(db, m, params_rows, ip_rows)
        if view is not None:
            found[key] = (m, view)
    return [report_rows(vid, sid, m, view) for (sid, vid), (m, view) in sorted(found.items())]


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
    if status == "published" and (not (reviewer or "").strip() or not (note or "").strip()):
        raise UnprocessableError("publishing requires reviewer and note")
    if status not in {"draft", "published"}:
        raise UnprocessableError("invalid report status")
    # Refresh any cached instance after acquiring the lock, so concurrent reviews
    # append to the latest history rather than overwriting an earlier review.
    r = db.query(ArchReport).filter_by(id=report_id).populate_existing().with_for_update().one_or_none()
    if r is None:
        raise NotFoundError(f"report not found: {report_id}")
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


def report_package(db: Session, report_id: str) -> tuple[bytes, str]:
    """Frozen body + cover/manifest (review history, input hashes, measurement ids) as one ZIP."""
    r = get_report(db, report_id)
    run_inputs: dict[str, dict[str, Any]] = {}
    for rid in r.exploration_run_refs or []:
        run = db.get(ArchExplorationRun, rid)
        if run is None:
            run_inputs[rid] = {"missing": True}
            continue
        run_inputs[rid] = {"input_hash": run.input_hash, "engine_rev": run.engine_rev, "created_at": run.created_at,
                           "variant_input_hashes": {f"{v['scenario_id']}/{v['variant_id']}": v.get("input_hash")
                                                    for v in run.variants or [] if v.get("variant_id")}}
    return package_zip(_report_meta(r), r.snapshot or {}, r.rendered_html, run_inputs, list(r.review_history or []))


def report_stale(db: Session, report_id: str) -> dict[str, Any]:
    """Current predictions that differ from the frozen snapshot (-> regenerate)."""
    r = get_report(db, report_id)
    changed = []
    snap_rows = (r.snapshot or {}).get("scenarios", [])
    keys = {(row["scenario_id"], row["variant_id"]) for row in snap_rows}
    current = {(sid, vid): pid for pid, sid, vid in db.query(Prediction.id, Prediction.scenario_ref, Prediction.variant_ref)
               .filter(Prediction.status == "current",
                       tuple_(Prediction.scenario_ref, Prediction.variant_ref).in_(keys)).all()} if keys else {}
    for row in snap_rows:
        cur = current.get((row["scenario_id"], row["variant_id"]))
        if cur != row.get("prediction_id"):
            changed.append({"variant_id": row["variant_id"], "snapshot": row.get("prediction_id"), "current": cur})
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
                        "option deltas are relative to the min-power (lossy allowed) case, not the registered IQ-keeping case"
                        if rule == "auto:min-power-iq" else
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
    # SQL aggregate (run, DVFS) -> count: the prediction metrics are never loaded
    q = db.query(Prediction.exploration_run_ref, Prediction.dvfs_table_ref, func.count()).filter(Prediction.status == "current")
    if project_ref:
        q = q.filter(Prediction.project_ref == project_ref)
    groups = q.group_by(Prediction.exploration_run_ref, Prediction.dvfs_table_ref).all()
    run_ids = {g[0] for g in groups}
    runs = {r.id: r for r in db.query(ArchExplorationRun.id, ArchExplorationRun.engine_rev, ArchExplorationRun.dvfs_table_ref)
            .filter(ArchExplorationRun.id.in_(run_ids)).all()} if run_ids else {}
    n_current = sum(g[2] for g in groups)
    engines: dict[str, int] = {}
    dvfs: dict[str, int] = {}
    unrecorded = 0
    for run_ref, pred_dvfs, count in groups:
        run = runs.get(run_ref)
        rev = run.engine_rev if run is not None else "unknown"
        engines[rev] = engines.get(rev, 0) + count
        ref = pred_dvfs or (run.dvfs_table_ref if run is not None else None)
        if ref:
            dvfs[ref] = dvfs.get(ref, 0) + count
        else:
            unrecorded += count

    mq = db.query(Evidence.provenance, Evidence.kpi).filter(Evidence.kind == "evidence.measurement")
    if project_ref:
        scenario_ids = [sid for (sid,) in db.query(Scenario.id).filter(Scenario.project_ref == project_ref).all()]
        mq = mq.filter(Evidence.scenario_ref.in_(scenario_ids)) if scenario_ids else mq.filter(Evidence.id.is_(None))
    real = synthetic = empty = unknown = 0
    for (prov, kpi) in mq.all():
        t = (kpi or {}).get("total_power_mw")
        origin = data_origin(prov)
        if (t.get("mean") if isinstance(t, dict) else t) is None:
            empty += 1  # import without power data: not evidence for the model
        elif origin == "synthetic":
            synthetic += 1
        elif origin == "physical_capture":
            real += 1
        else:
            unknown += 1  # no recorded collection method/device: never counted as silicon evidence

    R = ArchExplorationRun
    rq = db.query(R.id, R.engine_rev, R.created_at, R.summary,
                  func.jsonb_path_query_array(R.variants, literal_column("'$[*].model_lineage'::jsonpath")))  # lineages only, not the summaries
    if project_ref:
        rq = rq.filter(R.project_ref == project_ref)
    latest = rq.order_by(R.created_at.desc()).first()
    lineage = (run_lineage({"variants": [{"model_lineage": x} for x in latest[4] or []], "summary": latest.summary})[0]
               if latest is not None else None)
    return {
        "engine_rev": ENGINE_REV,
        "project_ref": project_ref,
        "predictions": {"current": n_current, "stale_engine": sum(n for e, n in engines.items() if e != ENGINE_REV),
                        "engines": engines},
        "dvfs": [{"ref": ref, "sample": _is_sample(ref), "predictions": n} for ref, n in sorted(dvfs.items())],
        "dvfs_unrecorded": unrecorded,
        "measurements": {"real": real, "synthetic": synthetic, "empty": empty, "unknown": unknown},
        "lineage": lineage,
        "latest_run": {"id": latest.id, "engine_rev": latest.engine_rev,
                       "created_at": latest.created_at.isoformat() if latest.created_at else None} if latest is not None else None,
    }


def prediction_freshness(db: Session, *, scenario_id: str | None = None, project_ref: str | None = None) -> dict[str, Any]:
    """Is each current prediction still the result of today's inputs? (PRED-04)

    Re-resolves every registered variant's inputs the way its run did (config profile, DVFS table) and compares the
    content-addressed input sections with the ones frozen in the run, plus the engine revision and the project's
    throughput judgement. Changed sections name the cause (variant_doc, ip:<id>, dvfs:<domain>, config, …).
    """
    from scenario_db.api.services.review_policy import project_policy
    from scenario_db.sim.arch_exploration import input_manifest

    q = db.query(Prediction.id, Prediction.scenario_ref, Prediction.variant_ref, Prediction.exploration_run_ref,
                 Prediction.project_ref, Prediction.metrics["throughput_model"].astext).filter(Prediction.status == "current")
    if scenario_id:
        q = q.filter(Prediction.scenario_ref == scenario_id)
    if project_ref:
        q = q.filter(Prediction.project_ref == project_ref)
    preds = q.all()
    runs = {r.id: r for r in db.query(ArchExplorationRun.id, ArchExplorationRun.engine_rev, ArchExplorationRun.project_ref,
                                      ArchExplorationRun.spec["input_selection"].label("selection"),
                                      ArchExplorationRun.spec["timing"].label("timing"),
                                      ArchExplorationRun.spec["timing_budget"].label("tb"),
                                      ArchExplorationRun.spec["throughput_from_policy"].label("policy_tp"))
            .filter(ArchExplorationRun.id.in_({p[3] for p in preds})).all()} if preds else {}
    policies: dict[str | None, Any] = {}
    rows = []
    for pid, sid, vid, run_id, proj, tp in preds:
        run = runs.get(run_id)
        reasons: list[str] = []
        changed: list[str] = []
        if run is None:
            rows.append({"prediction_id": pid, "scenario_id": sid, "variant_id": vid, "status": "unknown",
                         "reasons": ["run 없음"], "changed": []})
            continue
        if run.engine_rev != ENGINE_REV:
            reasons.append(f"engine {run.engine_rev} → {ENGINE_REV}")
        if proj not in policies:
            policies[proj] = project_policy(db, proj)
        pol = policies[proj]
        want_tp = (pol.throughput_model if pol and pol.throughput_model else "stage")
        if run.policy_tp is not False and (tp or "stage") != want_tp:
            reasons.append(f"판정 기준 {tp or 'stage'} → {want_tp}")
        frozen = (_run_variant_sections(db, run_id, sid, vid) or {})
        try:
            if run.selection is None:
                raise ValueError("run에 설정/DVFS 입력 선택 기록 없음 — 현재 입력과 비교할 수 없음")
            tb = TimingBudgetRequest(scenario_id=sid, variant_id=vid, **run.selection)
            shim = _shim(tb, vid)
            _apply_config_profile(db, shim)
            graph, tables, _ = _load(db, shim, tb.use_default_dvfs)
            from scenario_db.api.services.cpu import with_cpu_profile
            from scenario_db.sim.timing_budget import TimingBudgetOptions

            timing = TimingBudgetOptions.model_validate(run.timing or {})
            measured = (run.tb or {}).get("measured")
            if measured and measured.get("sw"):
                # Frozen resolved SW values describe the old run. Re-resolve its selected measurement,
                # retaining only the original caller's explicit overrides for today's manifest.
                from scenario_db.api.services.timing_budget import apply_measured
                from scenario_db.api.schemas.timing_budget import MeasuredInputs
                from scenario_db.sim.timing_budget import TimingStat

                timing = timing.model_copy(update={"task_runtime": {
                    k: TimingStat.model_validate(v) for k, v in (run.tb.get("task_runtime") or {}).items()}})
                timing = apply_measured(db, tb.model_copy(update={
                    "options": timing, "measured": MeasuredInputs.model_validate(measured)})).options
            if run.policy_tp is True:
                timing = timing.model_copy(update={"throughput_model": want_tp})
            timing = with_cpu_profile(db, timing, sid, vid)
            now, _ = input_manifest(graph, shim.config, tables, timing=timing)
            if frozen:
                changed = sorted(k for k in set(now) | set(frozen) if now.get(k) != frozen.get(k))
            else:
                reasons.append("run에 입력 manifest 없음 (이전 run)")
        except Exception as exc:  # noqa: BLE001 - one variant must not hide the others
            reasons.append(f"현재 입력 해석 실패: {str(exc)[:160]}")
        if changed:
            reasons.append("입력 변경: " + ", ".join(changed[:6]) + (f" 외 {len(changed) - 6}" if len(changed) > 6 else ""))
        rows.append({"prediction_id": pid, "scenario_id": sid, "variant_id": vid, "run_id": run_id,
                     "status": "stale" if reasons else "fresh", "reasons": reasons, "changed": changed})
    return {"rows": rows, "stale": sum(r["status"] == "stale" for r in rows), "fresh": sum(r["status"] == "fresh" for r in rows),
            "engine_rev": ENGINE_REV}


def _run_variant_sections(db: Session, run_id: str, scenario_id: str, variant_id: str) -> dict[str, str] | None:
    R = ArchExplorationRun
    return db.query(func.jsonb_path_query_first(
        R.variants, literal_column("'$[*] ? (@.scenario_id == $s && @.variant_id == $v).input_sections'::jsonpath"),
        func.jsonb_build_object(literal("s"), scenario_id, literal("v"), variant_id))).filter(R.id == run_id).scalar()
