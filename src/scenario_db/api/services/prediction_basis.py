"""Model basis (예측 기준) of a registered prediction — P0, derived from what the run recorded.

A prediction is defined by three independent axes:

* model basis: sim config profile (+version), power params (+version), DVFS table, exploration engine
* SW timing: a measured trace's SW build (``1.2.3 실측 · 2600``) or the scenario's defined (assumed) timing table,
  identified by a hash of the per-node ``sw_timing`` the run actually used (``정의 #a1b2c3``). A SW profile
  (``sw-vendor-v1.2.3``) is a release descriptor without timing values, so it never labels defined timing.
* variant data: scenario / variant YAML (reported by ``prediction_freshness`` as ``variant_doc`` changes)

No new table yet (P1): the basis is reconstructed from the run spec, the prediction's model lineage and
the profile / params catalogs, and given a short stable label (``cfg2 · pmp2 · e11``). Runs that did not
record their config selection (older engines) get ``미기록`` instead of a guess.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from scenario_db.db.models.capability import SwProfile
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.exploration import ArchExplorationRun, ModelBasis, Prediction


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


def soc_short(soc_ref: str | None) -> str | None:
    """``soc-exynos2600`` -> ``2600``."""
    if not soc_ref:
        return None
    tail = str(soc_ref).rsplit("-", 1)[-1]
    digits = "".join(ch for ch in tail if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else tail


def sw_timing_hash(variant_doc: dict[str, Any] | None) -> str | None:
    """Short content hash of the per-node ``sw_timing`` in a resolved variant document (None without any)."""
    nodes = (variant_doc or {}).get("node_configs") or {}
    timing = {k: v.get("sw_timing") for k, v in sorted(nodes.items()) if isinstance(v, dict) and v.get("sw_timing")}
    if not timing:
        return None
    import json

    return hashlib.sha256(json.dumps(timing, sort_keys=True, default=str).encode()).hexdigest()[:6]


def defined_timing_hash(db: Session, p: Prediction) -> str | None:
    """Hash of the SW timing the prediction's run used: its frozen ``variant_doc`` blob (manifest), None for runs
    without a manifest (older engines) — no guess from today's YAML."""
    from sqlalchemy import func, literal, literal_column

    R = ArchExplorationRun
    digest = db.query(func.jsonb_path_query_first(
        R.variants, literal_column("'$[*] ? (@.scenario_id == $s && @.variant_id == $v).input_sections.variant_doc'::jsonpath"),
        func.jsonb_build_object(literal("s"), p.scenario_ref, literal("v"), p.variant_ref))).filter(R.id == p.exploration_run_ref).scalar()
    if not digest:
        return None
    blob = db.query(R.spec["manifest"]["blobs"][str(digest)]).filter(R.id == p.exploration_run_ref).scalar()
    return sw_timing_hash(blob if isinstance(blob, dict) else None)


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
    meas_refs: set[str] = set()
    for r in runs.values():
        m = ((r.tb or {}).get("measured") or {}).get("measurement_ref")
        if m:
            meas_refs.add(str(m))
    meas_sw = dict(db.query(Evidence.id, Evidence.sw_baseline_ref).filter(Evidence.id.in_(meas_refs)).all()) if meas_refs else {}
    sw_soc = {r.id: soc_short(((r.metadata_ or {}).get("compatible_soc") or [None])[0])
              for r in db.query(SwProfile.id, SwProfile.metadata_).filter(SwProfile.id.in_(set(meas_sw.values()))).all()} if meas_sw else {}
    basis_ids = {str((r.selection or {}).get("basis_ref")) for r in runs.values() if (r.selection or {}).get("basis_ref")}
    registry = {b.id: b for b in db.query(ModelBasis).filter(ModelBasis.id.in_(basis_ids)).all()} if basis_ids else {}
    out: dict[str, dict[str, Any]] = {}
    for p in preds:
        run = runs.get(p.exploration_run_ref)
        sel = (run.selection or {}) if run is not None else {}
        cfg_ref = sel.get("config_profile_ref") or (run.profile if run is not None else None)
        recorded = bool(run is not None and run.selection is not None)
        lineage = ((p.metrics or {}).get("model_lineage") or {})
        pp_ref = lineage.get("power_params_ref") or (sel.get("config") or {}).get("power_params_ref")
        pp_id = _params_id(pp_ref)
        pp_ver = None
        if pp_ref and "@" in str(pp_ref):
            tail = str(pp_ref).split("@", 1)[1]
            pp_ver = int(tail) if tail.isdigit() else None
        cfg_version = None
        if cfg_ref and "@" in str(cfg_ref):
            tail = str(cfg_ref).split("@", 1)[1]
            cfg_version = int(tail) if tail.isdigit() else None
        basis = {
            "recorded": recorded,
            "config_profile_ref": cfg_ref, "config_version": cfg_version,
            "power_params_ref": pp_id, "power_params_version": pp_ver,
            "power_params_hash": lineage.get("power_params_hash"),
            "dvfs_table_ref": p.dvfs_table_ref or (run.dvfs_table_ref if run is not None else None),
            "engine_rev": run.engine_rev if run is not None else None,
        }
        reg = registry.get(str(sel.get("basis_ref"))) if sel.get("basis_ref") else None
        overrides = list(sel.get("basis_overrides") or [])
        basis["basis_id"] = reg.id if reg is not None else None
        basis["code"] = reg.code if reg is not None else None
        basis["basis_status"] = reg.status if reg is not None else None
        basis["overrides"] = overrides
        # registered basis -> its code (B3, B3* when inputs were set on top); otherwise the reconstructed components
        basis["label"] = f"{reg.code}{'*' if overrides else ''}" if reg is not None else basis_label(basis)
        basis["components"] = basis_label(basis)
        basis["key"] = hashlib.sha256("|".join(str(basis.get(k)) for k in (
            "recorded", "config_profile_ref", "config_version", "power_params_ref", "power_params_version",
            "power_params_hash", "dvfs_table_ref", "engine_rev")).encode()).hexdigest()[:12]
        mref = ((run.tb or {}).get("measured") or {}).get("measurement_ref") if run is not None else None
        measured_sw = bool(((run.tb or {}).get("measured") or {}).get("sw")) if run is not None else False
        sw_ref = meas_sw.get(str(mref)) if mref and measured_sw else None
        if sw_ref:
            soc = sw_soc.get(sw_ref)
            sw = {"ref": sw_ref, "source": "measured", "measurement_ref": mref, "soc": soc,
                  "label": f"{_sw_short(sw_ref)} 실측{f' · {soc}' if soc else ''}"}
        else:
            digest = defined_timing_hash(db, p) if run is not None else None
            sw = {"ref": None, "source": "defined", "measurement_ref": None, "soc": None, "hash": digest,
                  "label": f"정의 #{digest}" if digest else "정의값"}
        out[p.id] = {"basis": basis, "sw": sw}
    return out
