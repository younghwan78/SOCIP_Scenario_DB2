"""Model basis (예측 기준) — P1 registry + request resolution, P2 promotion.

A basis bundles the model inputs that decide a predicted number: sim config profile, power params (id@version),
DVFS table and the exploration engine revision. It never changes after creation; a change is a new basis whose
``parent_ref`` points at the old one. One basis per project is ``active``: requests that do not choose a basis and
do not set those inputs explicitly use it, so Timing Budget, exploration, simulation and registration agree.

SW timing is deliberately *not* part of a basis (compared per SW version / measured vs defined) and neither is the
variant data (scenario / variant YAML) — both are reported next to the basis label.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from scenario_db.db.models.capability import PowerModelParams, SimConfigProfile, SocDvfsTable
from scenario_db.db.models.definition import Project, Scenario
from scenario_db.db.models.exploration import ModelBasis
from scenario_db.exceptions import NotFoundError, UnprocessableError

BASIS_FIELDS = ("config_profile_ref", "power_params_ref", "dvfs_table_ref")


def _now() -> datetime:
    return datetime.now(UTC)


def content_hash(project_ref: str, config_profile_ref: str | None, power_params_ref: str | None,
                 dvfs_table_ref: str | None, engine_rev: str) -> str:
    raw = "|".join(str(x) for x in (project_ref, config_profile_ref, power_params_ref, dvfs_table_ref, engine_rev))
    return hashlib.sha256(raw.encode()).hexdigest()


def basis_dict(row: ModelBasis) -> dict[str, Any]:
    return {
        "id": row.id, "project_ref": row.project_ref, "seq": row.seq, "code": row.code, "title": row.title,
        "status": row.status, "config_profile_ref": row.config_profile_ref, "power_params_ref": row.power_params_ref,
        "dvfs_table_ref": row.dvfs_table_ref, "engine_rev": row.engine_rev, "content_hash": row.content_hash,
        "parent_ref": row.parent_ref, "notes": row.notes, "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "activated_by": row.activated_by, "activated_at": row.activated_at.isoformat() if row.activated_at else None,
        "components": basis_components(row),
    }


def basis_components(row: Any) -> str:
    """``cfg v2 · pmp v2 · dvfs-…-v0 · e11`` (for tooltips; the code is the short name)."""
    def ver(ref: str | None, prefix: str) -> str:
        if not ref:
            return f"{prefix} 기본"
        tail = str(ref).split("@", 1)
        return f"{prefix} v{tail[1]}" if len(tail) == 2 and tail[1].isdigit() else f"{prefix} {ref}"
    eng = str(getattr(row, "engine_rev", "") or "").rsplit("/", 1)[-1]
    return " · ".join([ver(row.config_profile_ref, "cfg"), ver(row.power_params_ref, "pmp"),
                       str(row.dvfs_table_ref or "DVFS 기본"), f"e{eng}" if eng.isdigit() else str(row.engine_rev)])


def _normalize_power_params(db: Session, ref: str | None) -> str | None:
    if not ref:
        return None
    pid, _, ver = str(ref).partition("@")
    row = db.get(PowerModelParams, pid)
    if row is None:
        raise NotFoundError(f"power_model_params not found: {ref}")
    if ver and (not ver.isdigit() or int(ver) != row.version):
        raise UnprocessableError(f"power_model_params '{pid}' is at version {row.version}, requested '{ver}'")
    return f"{pid}@{row.version}"


def _normalize_profile(db: Session, ref: str | None) -> str | None:
    if not ref:
        return None
    pid = str(ref).split("@", 1)[0]
    row = db.get(SimConfigProfile, pid)
    if row is None:
        raise NotFoundError(f"sim.config_profile not found: {ref}")
    return pid


def create_basis(db: Session, *, project_ref: str, config_profile_ref: str | None = None,
                 power_params_ref: str | None = None, dvfs_table_ref: str | None = None, title: str | None = None,
                 notes: str | None = None, parent_ref: str | None = None, user: str | None = None) -> dict[str, Any]:
    """New draft basis. The same content in the same project returns the existing basis (``existed``)."""
    from scenario_db.sim.arch_exploration import ENGINE_REV

    if db.get(Project, project_ref) is None:
        raise NotFoundError(f"project not found: {project_ref}")
    cfg = _normalize_profile(db, config_profile_ref)
    pp = _normalize_power_params(db, power_params_ref)
    if dvfs_table_ref and db.get(SocDvfsTable, dvfs_table_ref) is None:
        raise NotFoundError(f"DVFS table not found: {dvfs_table_ref}")
    if parent_ref and db.get(ModelBasis, parent_ref) is None:
        raise NotFoundError(f"basis not found: {parent_ref}")
    digest = content_hash(project_ref, cfg, pp, dvfs_table_ref, ENGINE_REV)
    same = db.query(ModelBasis).filter(ModelBasis.project_ref == project_ref, ModelBasis.content_hash == digest).first()
    if same is not None:
        return basis_dict(same) | {"existed": True}
    seq = int(db.query(func.coalesce(func.max(ModelBasis.seq), 0)).filter(ModelBasis.project_ref == project_ref).scalar() or 0) + 1
    row = ModelBasis(id=f"basis-{project_ref}-{seq}", project_ref=project_ref, seq=seq, code=f"B{seq}", title=title,
                     status="draft", config_profile_ref=cfg, power_params_ref=pp, dvfs_table_ref=dvfs_table_ref,
                     engine_rev=ENGINE_REV, content_hash=digest, parent_ref=parent_ref, notes=notes, trial={},
                     created_by=user, created_at=_now())
    db.add(row)
    db.commit()
    return basis_dict(row) | {"existed": False}


def list_bases(db: Session, project_ref: str) -> list[dict[str, Any]]:
    rows = db.query(ModelBasis).filter(ModelBasis.project_ref == project_ref).order_by(ModelBasis.seq.desc()).all()
    return [basis_dict(r) | {"trial": trial_summary(r)} for r in rows]


def get_basis(db: Session, basis_id: str) -> ModelBasis:
    row = db.get(ModelBasis, basis_id)
    if row is None:
        raise NotFoundError(f"basis not found: {basis_id}")
    return row


def active_basis(db: Session, project_ref: str | None) -> ModelBasis | None:
    if not project_ref:
        return None
    return db.query(ModelBasis).filter(ModelBasis.project_ref == project_ref, ModelBasis.status == "active").one_or_none()


def activate_basis(db: Session, basis_id: str, user: str | None = None, *, commit: bool = True) -> dict[str, Any]:
    """Make a basis the project's default; the previous active one is retired (kept for history)."""
    row = get_basis(db, basis_id)
    if row.status == "retired":
        raise UnprocessableError("a retired basis cannot be activated again; create a new basis from it")
    if row.status != "active":
        prev = active_basis(db, row.project_ref)
        if prev is not None:
            prev.status = "retired"
            db.flush()
        row.status = "active"
        row.activated_by = user
        row.activated_at = _now()
    if commit:
        db.commit()
    return basis_dict(row)


def retire_basis(db: Session, basis_id: str) -> dict[str, Any]:
    row = get_basis(db, basis_id)
    if row.status == "active":
        raise UnprocessableError("activate another basis first; the project always keeps its active basis")
    row.status = "retired"
    db.commit()
    return basis_dict(row)


def diff_bases(a: Any | None, b: Any) -> list[dict[str, Any]]:
    """Component changes a -> b (config profile / power params / DVFS / engine)."""
    out = []
    for key in (*BASIS_FIELDS, "engine_rev"):
        old, new = (getattr(a, key, None) if a is not None else None), getattr(b, key, None)
        if old != new:
            out.append({"field": key, "from": old, "to": new})
    return out


# ------------------------------------------------------------------- request resolution
def _project_of(db: Session, request: Any) -> str | None:
    sid = getattr(request, "scenario_id", None)
    if not sid:
        return None
    row = db.get(Scenario, sid)
    return row.project_ref if row is not None else None


def apply_basis(db: Session, request: Any, project_ref: str | None = None) -> ModelBasis | None:
    """Fill a request's config profile / power params / DVFS table from its basis.

    ``basis_ref`` given -> that basis; else the project's active basis. Explicit request values win and are listed in
    ``basis_overrides`` (an ad-hoc condition: shown as ``B3*``). No basis at all -> unchanged (code defaults).
    Idempotent: re-applying to an already resolved request changes nothing.
    """
    if not hasattr(request, "basis_ref"):
        return None
    if request.basis_ref:
        basis = get_basis(db, request.basis_ref)
    else:
        project = project_ref or _project_of(db, request)
        basis = active_basis(db, project) if isinstance(project, str) else None
    if basis is None or not isinstance(getattr(basis, "id", None), str):
        return None
    overrides: list[str] = list(getattr(request, "basis_overrides", None) or [])
    cfg_explicit = request.config_profile_ref
    if cfg_explicit and cfg_explicit.split("@", 1)[0] != (basis.config_profile_ref or ""):
        overrides.append("config_profile")
    elif not cfg_explicit and basis.config_profile_ref:
        request.config_profile_ref = basis.config_profile_ref
    config = request.config
    pp_explicit = "power_params_ref" in config.model_fields_set or config.power_params is not None
    if pp_explicit:
        mine = (config.power_params_ref or "").split("@", 1)[0]
        if config.power_params is not None or mine != (basis.power_params_ref or "").split("@", 1)[0]:
            overrides.append("power_params")
    elif basis.power_params_ref:
        request.config = config.model_copy(update={"power_params_ref": basis.power_params_ref})
    if getattr(request, "dvfs_tables", None):
        overrides.append("dvfs")
    elif request.dvfs_table_ref and request.dvfs_table_ref != basis.dvfs_table_ref:
        overrides.append("dvfs")
    elif not request.dvfs_table_ref and basis.dvfs_table_ref:
        request.dvfs_table_ref = basis.dvfs_table_ref
    request.basis_ref = basis.id
    request.basis_overrides = sorted(set(overrides))
    return basis


# ------------------------------------------------------------------- P2 promotion (trial)
def trial_summary(row: ModelBasis) -> dict[str, Any]:
    items = list((row.trial or {}).get("items", {}).values())
    done = [i for i in items if i.get("status") == "ok"]
    deltas = [i["delta_mw"] for i in done if i.get("delta_mw") is not None]
    return {"total": (row.trial or {}).get("total", 0), "done": len(done),
            "skipped": sum(i.get("status") == "skipped" for i in items), "failed": sum(i.get("status") == "error" for i in items),
            "delta_mw_sum": round(sum(deltas), 1) if deltas else None,
            "delta_mw_min": round(min(deltas), 1) if deltas else None, "delta_mw_max": round(max(deltas), 1) if deltas else None,
            "started_at": (row.trial or {}).get("started_at"), "promoted_at": (row.trial or {}).get("promoted_at")}


def _trial_items(row: ModelBasis) -> dict[str, dict[str, Any]]:
    return dict(((row.trial or {}).get("items") or {}))


def start_trial(db: Session, basis_id: str, user: str | None = None) -> dict[str, Any]:
    """Snapshot the project's current predictions as the trial set of a draft basis (P2 step 1)."""
    from scenario_db.db.models.exploration import Prediction

    row = get_basis(db, basis_id)
    if row.status != "draft":
        raise UnprocessableError("only a draft basis is tried; the active one is already the default")
    preds = db.query(Prediction).filter(Prediction.project_ref == row.project_ref, Prediction.status == "current") \
        .order_by(Prediction.scenario_ref, Prediction.variant_ref).all()
    items = {p.id: {"prediction_id": p.id, "scenario_id": p.scenario_ref, "variant_id": p.variant_ref, "status": "pending",
                    "old_total_mw": ((p.metrics or {}).get("power") or {}).get("total_mw")} for p in preds}
    row.trial = {"started_at": _now().isoformat(), "started_by": user, "total": len(items), "items": items}
    db.commit()
    return get_trial(db, basis_id)


def run_trial_item(db: Session, basis_id: str, prediction_id: str, user: str | None = None) -> dict[str, Any]:
    """Dry-run one current prediction under the draft basis: a run is created, nothing is registered (P2 step 2)."""
    from scenario_db.api.services.recompute import recompute_prediction

    row = get_basis(db, basis_id)
    items = _trial_items(row)
    if prediction_id not in items:
        raise NotFoundError(f"prediction {prediction_id} is not in the trial of {row.code}; restart the trial")
    try:
        res = recompute_prediction(db, prediction_id, basis=row, dry_run=True, user=user,
                                   reason=f"기준 {row.code} 시험 계산")
    except (NotFoundError, UnprocessableError) as exc:
        db.rollback()
        res = {"status": "error", "reason": str(exc)[:300]}
    row = get_basis(db, basis_id)  # the run creation committed; reload before writing the trial back
    items = _trial_items(row)
    items[prediction_id] = {**items[prediction_id], **{k: v for k, v in res.items() if k not in ("prediction_id",)},
                            "tried_at": _now().isoformat()}
    row.trial = {**(row.trial or {}), "items": items}
    db.commit()
    return items[prediction_id]


def get_trial(db: Session, basis_id: str) -> dict[str, Any]:
    row = get_basis(db, basis_id)
    prev = active_basis(db, row.project_ref)
    return {"basis": basis_dict(row), "against": basis_dict(prev) if prev is not None and prev.id != row.id else None,
            "diff": diff_bases(prev if prev is not None and prev.id != row.id else None, row),
            "summary": trial_summary(row), "items": sorted(_trial_items(row).values(),
                                                          key=lambda i: (i.get("scenario_id") or "", i.get("variant_id") or ""))}


def promote_basis(db: Session, basis_id: str, user: str | None = None, *, reason: str | None = None) -> dict[str, Any]:
    """Register every successful trial item and make the basis active, in one transaction (P2 step 3).

    An item whose prediction changed after its trial (someone registered meanwhile) is not overwritten: it is reported
    as ``stale`` and keeps its current prediction. Pending / failed / skipped items also keep theirs.
    """
    from scenario_db.api.schemas.arch_exploration import ExpectedCurrentPrediction, PromoteRequest
    from scenario_db.api.services.arch_exploration import promote
    from scenario_db.exceptions import ConflictError

    row = get_basis(db, basis_id)
    if row.status != "draft":
        raise UnprocessableError("only a draft basis is promoted")
    items = _trial_items(row)
    if not items:
        raise UnprocessableError("run the trial first (기준 시험 계산)")
    why = reason or f"기준 {row.code} 승격"
    promoted, kept = [], []
    for pid, it in items.items():
        if it.get("status") != "ok" or not it.get("run_id"):
            kept.append({"prediction_id": pid, "variant_id": it.get("variant_id"), "reason": it.get("reason") or it.get("status")})
            continue
        req = PromoteRequest(run_id=it["run_id"], scenario_id=it["scenario_id"], variant_ids=[it["variant_id"]],
                             case_key=it.get("case_key"), reason=why, expected_project_ref=row.project_ref,
                             expected_current=[ExpectedCurrentPrediction(scenario_id=it["scenario_id"], variant_id=it["variant_id"],
                                                                         prediction_id=pid)])
        try:
            out = promote(db, req, user, rule=it.get("rule") if it.get("case_key") else None, commit=False)
        except ConflictError:
            kept.append({"prediction_id": pid, "variant_id": it.get("variant_id"), "reason": "stale: 시험 후 다른 등록이 있음"})
            continue
        if out.get("promoted"):
            promoted.append({"prediction_id": pid, "variant_id": it["variant_id"], "new_prediction_id": out["promoted"][0]["id"],
                             "delta_mw": it.get("delta_mw")})
        else:
            kept.append({"prediction_id": pid, "variant_id": it.get("variant_id"),
                         "reason": "; ".join(s.get("reason", "") for s in out.get("skipped") or []) or "not promoted"})
    activate_basis(db, basis_id, user, commit=False)
    row = get_basis(db, basis_id)
    row.trial = {**(row.trial or {}), "promoted_at": _now().isoformat(), "promoted_by": user,
                 "result": {"promoted": len(promoted), "kept": len(kept)}}
    db.commit()
    return {"basis": basis_dict(row), "promoted": promoted, "kept": kept}
