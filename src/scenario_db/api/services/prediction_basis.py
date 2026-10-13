"""Model basis (예측 기준) of a registered prediction — P0, derived from what the run recorded.

A prediction is defined by three independent axes:

* model basis: sim config profile (+version), power params (+version), DVFS table, exploration engine
* SW timing: the SW version whose task timing went in (measured trace's SW, else the project default)
* variant data: scenario / variant YAML (reported by ``prediction_freshness`` as ``variant_doc`` changes)

No new table yet (P1): the basis is reconstructed from the run spec, the prediction's model lineage and
the profile / params catalogs, and given a short stable label (``cfg2 · pmp2 · e11``). Runs that did not
record their config selection (older engines) get ``미기록`` instead of a guess.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import PowerModelParams, SimConfigProfile
from scenario_db.db.models.definition import Project
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ArchExplorationRun, Prediction


def _engine_short(rev: str | None) -> str:
    if not rev:
        return "e?"
    tail = str(rev).rsplit("/", 1)[-1]
    return f"e{tail}" if tail.isdigit() else str(rev)


def _sw_short(ref: str | None) -> str | None:
    if not ref:
        return None
    s = str(ref)
    for prefix in ("sw-vendor-v", "sw-vendor-", "sw-"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def _params_id(ref: str | None) -> str | None:
    return str(ref).split("@", 1)[0] if ref else None


def basis_label(b: dict[str, Any]) -> str:
    """``cfg2 · pmp2 · e11`` — or ``미기록 · e9`` when the run kept no config selection."""
    eng = _engine_short(b.get("engine_rev"))
    if not b.get("recorded"):
        return f"미기록 · {eng}"
    cfg = f"cfg{b['config_version']}" if b.get("config_version") is not None else ("cfg?" if b.get("config_profile_ref") else "cfg 기본")
    pmp = (f"pmp{b['power_params_version']}" if b.get("power_params_version") is not None
           else ("pmp?" if b.get("power_params_ref") else "pmp 기본"))
    return f"{cfg} · {pmp} · {eng}"


def prediction_bases(db: Session, preds: list[Prediction]) -> dict[str, dict[str, Any]]:
    """prediction id -> {basis: {...}, sw: {...}} for the given predictions (current or superseded)."""
    if not preds:
        return {}
    run_ids = {p.exploration_run_ref for p in preds}
    R = ArchExplorationRun
    runs = {r.id: r for r in db.query(R.id, R.engine_rev, R.dvfs_table_ref, R.spec["config_profile_ref"].label("profile"),
                                      R.spec["input_selection"].label("selection"), R.spec["timing_budget"].label("tb"))
            .filter(R.id.in_(run_ids)).all()}
    profiles = {r.id: r for r in db.query(SimConfigProfile.id, SimConfigProfile.version, SimConfigProfile.run_config).all()}
    params = {r.id: r.version for r in db.query(PowerModelParams.id, PowerModelParams.version).all()}
    meas_refs: set[str] = set()
    for r in runs.values():
        m = ((r.tb or {}).get("measured") or {}).get("measurement_ref")
        if m:
            meas_refs.add(str(m))
    meas_sw = dict(db.query(Evidence.id, Evidence.sw_baseline_ref).filter(Evidence.id.in_(meas_refs)).all()) if meas_refs else {}
    project_sw: dict[str, str | None] = {}
    for pid in {p.project_ref for p in preds if p.project_ref}:
        proj = db.get(Project, pid)
        meta = (getattr(proj, "metadata_", None) or {}) if proj else {}
        glob = (getattr(proj, "globals_", None) or {}) if proj else {}
        project_sw[pid] = meta.get("default_sw_profile_ref") or glob.get("default_sw_profile_ref")

    out: dict[str, dict[str, Any]] = {}
    for p in preds:
        run = runs.get(p.exploration_run_ref)
        sel = (run.selection or {}) if run is not None else {}
        cfg_ref = sel.get("config_profile_ref") or (run.profile if run is not None else None)
        recorded = bool(run is not None and run.selection is not None)
        prof = profiles.get(cfg_ref) if cfg_ref else None
        lineage = ((p.metrics or {}).get("model_lineage") or {})
        pp_ref = (lineage.get("power_params_ref") or (sel.get("config") or {}).get("power_params_ref")
                  or ((prof.run_config or {}).get("power_params_ref") if prof is not None else None))
        pp_id = _params_id(pp_ref)
        pp_ver = None
        if pp_ref and "@" in str(pp_ref):
            tail = str(pp_ref).split("@", 1)[1]
            pp_ver = int(tail) if tail.isdigit() else None
        if pp_ver is None and pp_id in params:
            pp_ver = params[pp_id]
        basis = {
            "recorded": recorded,
            "config_profile_ref": cfg_ref, "config_version": prof.version if prof is not None else None,
            "power_params_ref": pp_id, "power_params_version": pp_ver,
            "power_params_hash": lineage.get("power_params_hash"),
            "dvfs_table_ref": p.dvfs_table_ref or (run.dvfs_table_ref if run is not None else None),
            "engine_rev": run.engine_rev if run is not None else None,
        }
        basis["label"] = basis_label(basis)
        basis["key"] = hashlib.sha256("|".join(str(basis.get(k)) for k in (
            "recorded", "config_profile_ref", "config_version", "power_params_ref", "power_params_version",
            "dvfs_table_ref", "engine_rev")).encode()).hexdigest()[:12]
        mref = ((run.tb or {}).get("measured") or {}).get("measurement_ref") if run is not None else None
        sw_ref = meas_sw.get(str(mref)) if mref else None
        sw = ({"ref": sw_ref, "source": "measured", "measurement_ref": mref} if sw_ref
              else {"ref": project_sw.get(p.project_ref), "source": "defined", "measurement_ref": None})
        sw["label"] = _sw_short(sw["ref"]) or "SW ?"
        out[p.id] = {"basis": basis, "sw": sw}
    return out
