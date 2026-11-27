"""Batch refresh of a project's current predictions after an engine / input change.

``recompute_prediction`` re-runs one prediction (one new exploration run each). After an engine revision or a shared
input change every prediction of a project goes stale at once; this module re-runs each registered exploration run
**once** under its stored condition and promotes every variant it registered by the default rule:

- exploration registrations: one new run per source run, scoped to the variants it registered.
- variants without a current prediction (e.g. an fps fail) are re-evaluated too, each under the condition of the
  newest run that evaluated it: a project report takes them from that run, so leaving them out keeps old-engine
  rows in the report (``stale_engine`` blocker). They are evaluated, not registered.
- timing-budget registrations: ``recompute_prediction`` each (they are registered conditions, not exploration runs).
- hand-picked registrations (``user:`` / ``lever:`` rules, runs with applied options) cannot be reproduced by the
  default rule and are reported as skipped.

``check=True`` computes everything without storing (rolled back) so the change can be reviewed first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.exceptions import NotFoundError

HAND_PICKED_PREFIXES = ("user:", "lever:")


@dataclass
class RunGroup:
    run_id: str
    scenario_type: str
    registered: list[Any] = field(default_factory=list)      # current predictions registered from this run
    extra: list[tuple[str, str]] = field(default_factory=list)  # run variants without a current prediction


@dataclass
class RefreshPlan:
    groups: list[RunGroup] = field(default_factory=list)
    timing_budget: list[Any] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


def plan_refresh(preds: list[Any], runs: dict[str, Any]) -> RefreshPlan:
    """Group the current predictions by their source run (pure; ``runs`` = every run of the project, id → row).

    A variant without a current prediction is re-evaluated once, under the condition of the newest run that
    evaluated it — the run a project report takes it from (``_project_run``). That run may register nothing."""
    plan = RefreshPlan()
    by_run: dict[str, RunGroup] = {}
    for p in sorted(preds, key=lambda p: (str(p.scenario_ref), str(p.variant_ref))):
        run = runs.get(p.exploration_run_ref)
        if run is None:
            plan.skipped.append(_skip(p, "등록한 exploration run이 없음 — 다시 등록 필요"))
            continue
        if str(p.selection_rule or "").startswith(HAND_PICKED_PREFIXES) or (run.spec or {}).get("apply_options"):
            plan.skipped.append(_skip(p, f"사람이 고른 조합 ({p.selection_rule}) — 조합 탐색에서 다시 선택 필요"))
            continue
        if run.scenario_type == "timing-budget":
            plan.timing_budget.append(p)
            continue
        group = by_run.setdefault(run.id, RunGroup(run.id, run.scenario_type))
        group.registered.append(p)
    registered = {(p.scenario_ref, p.variant_ref) for p in preds}
    claimed: set[tuple[str, str]] = set()
    for run in sorted(runs.values(), key=lambda r: (r.created_at, r.id), reverse=True):  # newest first, as the report
        for v in run.variants or []:
            key = (v.get("scenario_id"), v.get("variant_id"))
            if not (key[0] and key[1]) or key in registered or key in claimed:
                continue
            claimed.add(key)
            if run.scenario_type == "timing-budget" or (run.spec or {}).get("apply_options"):
                plan.skipped.append({"prediction_id": None, "scenario_id": key[0], "variant_id": key[1],
                                     "status": "skipped",
                                     "reason": f"미등록 variant의 최신 평가({run.id})가 재현할 수 없는 조건 — 직접 재탐색 필요"})
                continue
            by_run.setdefault(run.id, RunGroup(run.id, run.scenario_type)).extra.append(key)
    plan.groups = sorted(by_run.values(), key=lambda g: (runs[g.run_id].created_at, g.run_id))
    return plan


def _skip(p: Any, reason: str) -> dict[str, Any]:
    return {"prediction_id": p.id, "scenario_id": p.scenario_ref, "variant_id": p.variant_ref, "status": "skipped",
            "reason": reason}


def _old_total(p: Any) -> float | None:
    return ((p.metrics or {}).get("power") or {}).get("total_mw")


def _rerun_request(run: Any, group: RunGroup) -> Any:
    from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest
    from scenario_db.api.services.recompute import _SEL_KEYS, rerun_timing, variant_spec

    spec = rerun_timing(dict(run.spec or {}))
    sel = dict(spec.get("input_selection") or {})
    keys = sorted({(p.scenario_ref, p.variant_ref) for p in group.registered} | set(group.extra))
    variants = sorted({v for _, v in keys})
    return ArchExplorationRunRequest(
        title=f"일괄 재계산 · {run.scenario_type}", scenario_type=run.scenario_type,
        scenario_ids=sorted({s for s, _ in keys}), variant_ids=variants, include_derived=True,
        max_variants=len(variants), config=dict(sel.get("config") or {}),
        power_budget_from_reference=bool(spec.get("power_budget_from_reference")),
        spec=variant_spec(spec), **{k: sel[k] for k in _SEL_KEYS if k in sel})


def refresh_project(db: Session, project_ref: str, *, user: str | None = None, check: bool = False,
                    reason: str | None = None, parallel: bool = False) -> dict[str, Any]:
    """Re-run and re-register the project's current predictions (see the module doc).

    The exploration part is one transaction: every run and registration is stored together, or nothing is."""
    from scenario_db.api.schemas.arch_exploration import ExpectedCurrentPrediction, PromoteRequest
    from scenario_db.api.services.arch_exploration import default_case, promote, run_exploration
    from scenario_db.api.services.recompute import recompute_prediction
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
    from scenario_db.sim.arch_exploration import ENGINE_REV

    preds = db.query(Prediction).filter(Prediction.project_ref == project_ref, Prediction.status == "current").all()
    if not preds:
        raise NotFoundError(f"no current prediction in project {project_ref}")
    runs = {r.id: r for r in db.query(ArchExplorationRun).filter(ArchExplorationRun.project_ref == project_ref).all()}
    plan = plan_refresh(preds, runs)
    why = reason or "일괄 재계산 (engine · 입력 변경 반영)"
    rows: list[dict[str, Any]] = list(plan.skipped)
    new_runs: list[dict[str, Any]] = []
    try:
        for group in plan.groups:
            source = runs[group.run_id]
            new = run_exploration(db, _rerun_request(source, group), user, commit=False, parallel=parallel)
            new_runs.append({"source_run": source.id, "run_id": new["id"], "scenario_type": source.scenario_type,
                             "registered": len(group.registered), "extra": len(group.extra)})
            summaries = {(v.get("scenario_id"), v.get("variant_id")): v for v in new.get("variants") or []}
            promoted: dict[str, dict[str, Any]] = {}
            refused: dict[str, str] = {}
            if not check:
                for scenario in sorted({p.scenario_ref for p in group.registered}):
                    ps = [p for p in group.registered if p.scenario_ref == scenario]
                    out = promote(db, PromoteRequest(
                        run_id=new["id"], scenario_id=scenario, variant_ids=[p.variant_ref for p in ps], reason=why,
                        expected_project_ref=project_ref,
                        expected_current=[ExpectedCurrentPrediction(scenario_id=scenario, variant_id=p.variant_ref,
                                                                    prediction_id=p.id) for p in ps]),
                        user, commit=False)
                    promoted |= {f"{scenario}/{x['variant_id']}": x for x in out.get("promoted") or []}
                    refused |= {f"{scenario}/{x['variant_id']}": x.get("reason", "") for x in out.get("skipped") or []}
            for p in group.registered:
                key = f"{p.scenario_ref}/{p.variant_ref}"
                summary = summaries.get((p.scenario_ref, p.variant_ref))
                if check:
                    case, _ = default_case(db, project_ref, summary) if summary else (None, None)
                    new_mw, status = (case or {}).get("total_mw"), "ok" if case else "skipped"
                    note = None if case else "; ".join((summary or {}).get("spec_reasons") or ["no eligible case"])
                elif key in promoted:
                    new_mw, status, note = promoted[key].get("total_mw"), "recomputed", None
                else:
                    new_mw, status, note = None, "skipped", refused.get(key) or "no eligible case"
                rows.append(_row(p, new["id"], new_mw, status, note))
            for scenario, variant in group.extra:
                summary = summaries.get((scenario, variant))
                error = next((e.get("error") or e.get("message") or "calculation failed" for e in new.get("errors") or []
                              if (e.get("scenario_id"), e.get("variant_id")) == (scenario, variant)), None)
                rows.append({"prediction_id": None, "scenario_id": scenario, "variant_id": variant, "run_id": new["id"],
                             "status": "evaluated" if summary is not None else "error",
                             "spec_ok": (summary or {}).get("spec_ok"),
                             "reason": error or "; ".join((summary or {}).get("spec_reasons") or []) or None})
        if check:
            db.rollback()
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise
    for p in plan.timing_budget:
        if check:
            rows.append(_row(p, None, None, "pending", "timing-budget 등록 — 확인 모드에서는 계산하지 않음"))
            continue
        res = recompute_prediction(db, p.id, reason=why, user=user)
        rows.append(_row(p, res.get("run_id"), res.get("new_total_mw"), res.get("status", "skipped"), res.get("reason")))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"project_ref": project_ref, "engine_rev": ENGINE_REV, "check": check, "runs": new_runs,
            "counts": counts, "rows": rows}


def _row(p: Any, run_id: str | None, new_mw: float | None, status: str, note: str | None) -> dict[str, Any]:
    old = _old_total(p)
    return {"prediction_id": p.id, "scenario_id": p.scenario_ref, "variant_id": p.variant_ref, "run_id": run_id,
            "status": status, "old_total_mw": old, "new_total_mw": new_mw,
            "delta_mw": round(new_mw - old, 3) if new_mw is not None and old is not None else None,
            "reason": note}
