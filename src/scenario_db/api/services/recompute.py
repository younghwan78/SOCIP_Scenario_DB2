"""S5: re-run a registered prediction under its own stored condition (optionally with other power params).

- timing-budget registrations: the stored Timing Budget condition (options, config, profile, DVFS, measured inputs)
  is registered again (rule manual:timing-budget). A measured SW input is re-read from the measurement.
- exploration registrations: the stored exploration spec is re-run for that variant and the default rule promotes
  (a case picked by hand cannot be reproduced automatically and is skipped).
The previous prediction is superseded as usual, so history / attribution show what the new params changed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from scenario_db.exceptions import NotFoundError, UnprocessableError

_SPEC_KEYS = ("axes", "constraints", "objective", "timing", "top_n", "max_cases_per_variant", "verify", "verify_tolerance_pct")
_SEL_KEYS = ("config_profile_ref", "dvfs_tables", "dvfs_table_ref", "soc_ref", "dvfs_version", "use_default_dvfs")


def recompute_prediction(db: Session, prediction_id: str, *, power_params_ref: str | None = None,
                         reason: str | None = None, user: str | None = None) -> dict[str, Any]:
    from scenario_db.db.models.exploration import ArchExplorationRun, Prediction

    pred = db.get(Prediction, prediction_id)
    if pred is None:
        raise NotFoundError(f"prediction not found: {prediction_id}")
    if pred.status != "current":
        raise UnprocessableError("only the current prediction of a variant is recomputed")
    run = db.get(ArchExplorationRun, pred.exploration_run_ref)
    if run is None:
        raise UnprocessableError("the prediction's exploration run is gone; register it again")
    spec = dict(run.spec or {})
    sel = dict(spec.get("input_selection") or {})
    config = dict(sel.get("config") or {})
    if power_params_ref:
        config.pop("power_params", None)
        config["power_params_ref"] = power_params_ref
    old_total = ((pred.metrics or {}).get("power") or {}).get("total_mw")
    if isinstance(spec.get("timing"), dict):
        # the run stores the full option dump; a field left at its default must stay "unset" (e.g. ``cpu``: unset =
        # coefficients from the power params, set = the code default)
        from scenario_db.sim.timing_budget import TimingBudgetOptions

        defaults = TimingBudgetOptions().model_dump(mode="json")
        spec["timing"] = {k: v for k, v in spec["timing"].items() if k not in defaults or v != defaults[k]}
    if spec.get("throughput_from_policy") and isinstance(spec.get("timing"), dict):
        # the judgement followed the project policy: follow today's policy, not the frozen value
        spec["timing"] = {k: v for k, v in spec["timing"].items() if k != "throughput_model"}
    why = reason or (f"재계산 · power params {power_params_ref}" if power_params_ref else "재계산 (입력 변경 반영)")
    if run.scenario_type == "timing-budget":
        from scenario_db.api.schemas.timing_budget import TimingBudgetRegisterRequest
        from scenario_db.api.services.timing_budget import register_condition

        timing = dict(spec.get("timing") or {})
        measured = ((spec.get("timing_budget") or {}).get("measured")) or None
        if measured and measured.get("sw"):
            timing.pop("task_runtime", None)          # re-read the measurement
        if measured and measured.get("cpu"):
            timing.pop("cpu_profile", None)
        req = TimingBudgetRegisterRequest(scenario_id=pred.scenario_ref, variant_id=pred.variant_ref, options=timing,
                                          config=config, measured=measured, reason=why, expected_project_ref=pred.project_ref,
                                          **{k: sel[k] for k in _SEL_KEYS if k in sel})
        out = register_condition(db, req, user)
    else:
        if str(pred.selection_rule or "").startswith("user:"):
            return {"prediction_id": pred.id, "variant_id": pred.variant_ref, "status": "skipped",
                    "reason": f"사람이 고른 조합 ({pred.selection_rule}) — 조합 탐색에서 다시 선택 필요"}
        from scenario_db.api.schemas.arch_exploration import ArchExplorationRunRequest, PromoteRequest
        from scenario_db.api.services.arch_exploration import promote, run_exploration

        req = ArchExplorationRunRequest(
            title=f"재계산 · {pred.variant_ref}", scenario_type=run.scenario_type, scenario_ids=[pred.scenario_ref],
            variant_ids=[pred.variant_ref], include_derived=True, max_variants=1, config=config,
            spec={k: spec[k] for k in _SPEC_KEYS if k in spec}, **{k: sel[k] for k in _SEL_KEYS if k in sel})
        new_run = run_exploration(db, req, user)
        out = promote(db, PromoteRequest(run_id=new_run["id"], scenario_id=pred.scenario_ref, variant_ids=[pred.variant_ref],
                                         reason=why, expected_project_ref=pred.project_ref), user)
    promoted = out.get("promoted") or []
    if not promoted:
        return {"prediction_id": pred.id, "variant_id": pred.variant_ref, "status": "skipped",
                "reason": "; ".join(s.get("reason", "") for s in out.get("skipped") or []) or "no eligible case"}
    new_total = promoted[0].get("total_mw")
    return {"prediction_id": pred.id, "variant_id": pred.variant_ref, "scenario_id": pred.scenario_ref, "status": "recomputed",
            "new_prediction_id": promoted[0]["id"], "old_total_mw": old_total, "new_total_mw": new_total,
            "delta_mw": round(new_total - old_total, 3) if new_total is not None and old_total is not None else None}
