"""S5: fit power-model coefficients to measurements and publish them as a new (draft) power_model_params version.

Each usable measurement is predicted with the Timing Budget under one reproducible condition (SW statistic, the
measured SW runtime as input when the measurement has it, the base params) and compared per rail category with
the measurement (same rail rules as the Calibration page). Per category a single factor k minimises the squared
error through the origin (k = Σ p·m / Σ p²): CPU scales the CPU EM tables, BW scales the memory model
coefficients, IP becomes ``calibration.ip_power_scale["*"]`` (applied by the engine). Nothing is overwritten:
the result is a new draft params version with the fit recorded as lineage.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import yaml
from sqlalchemy import func
from sqlalchemy.orm import Session

from scenario_db.exceptions import NotFoundError, UnprocessableError

CATS = ("cpu", "ip", "bw")
K_RANGE = (0.2, 5.0)


def _base_ref(db: Session, base_params_ref: str | None, config_profile_ref: str | None) -> str:
    if base_params_ref:
        return base_params_ref
    if config_profile_ref:
        from scenario_db.db.models.capability import SimConfigProfile

        row = db.get(SimConfigProfile, config_profile_ref)
        ref = ((row.run_config or {}).get("power_params_ref") if row is not None else None)
        if ref:
            return str(ref)
    raise UnprocessableError("base power params is required (power_params_ref or a config profile that sets it)")


def _params_row(db: Session, ref: str):
    from scenario_db.db.models.capability import PowerModelParams as Row

    pid, _, ver = ref.partition("@")
    row = db.get(Row, pid)
    if row is None:
        raise NotFoundError(f"power_model_params not found: {ref}")
    if ver and int(ver) != row.version:
        raise UnprocessableError(f"power_model_params '{pid}' is at version {row.version}, requested {ver}")
    return row


def _measurements(db: Session, project_ref: str, scenario_id: str | None, include_synthetic: bool):
    from scenario_db.api.services.calibration import is_synthetic
    from scenario_db.db.models.definition import Scenario
    from scenario_db.db.models.evidence import Evidence

    scen = {s.id: s.project_ref for s in db.query(Scenario.id, Scenario.project_ref).all()}
    q = db.query(Evidence).filter(Evidence.kind == "evidence.measurement")
    if scenario_id:
        q = q.filter(Evidence.scenario_ref == scenario_id)
    out = []
    for m in q.order_by(Evidence.scenario_ref, Evidence.variant_ref, Evidence.id).all():
        if (m.project_ref or scen.get(m.scenario_ref)) != project_ref:
            continue
        synthetic = is_synthetic(m.provenance)
        if synthetic and not include_synthetic:
            continue
        if not m.vdd_power:
            continue
        out.append((m, synthetic))
    return out


def _fit(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """k minimising Σ (k·p − m)² (through the origin) and the error before / after."""
    pairs = [(p, m) for p, m in pairs if p and p > 0 and m is not None]
    if not pairs:
        return {"k": None, "n": 0}
    spp = sum(p * p for p, _ in pairs)
    raw = sum(p * m for p, m in pairs) / spp if spp else 1.0
    k = min(K_RANGE[1], max(K_RANGE[0], raw))
    mean_m = sum(m for _, m in pairs) / len(pairs)
    sst = sum((m - mean_m) ** 2 for _, m in pairs)

    def err(scale: float) -> tuple[float, float, float]:
        sse = sum((scale * p - m) ** 2 for p, m in pairs)
        mape = 100.0 * sum(abs(scale * p - m) / m for p, m in pairs if m) / max(1, sum(1 for _, m in pairs if m))
        return math.sqrt(sse / len(pairs)), mape, sse

    rmse0, mape0, _ = err(1.0)
    rmse1, mape1, sse1 = err(k)
    return {"k": round(k, 4), "k_raw": round(raw, 4), "clamped": k != raw, "n": len(pairs),
            "rmse_before_mw": round(rmse0, 2), "rmse_after_mw": round(rmse1, 2),
            "mape_before_pct": round(mape0, 1), "mape_after_pct": round(mape1, 1),
            "r2_after": round(1 - sse1 / sst, 3) if sst > 0 else None}


def fit_proposal(db: Session, req: Any) -> dict[str, Any]:
    from scenario_db.api.schemas.timing_budget import MeasuredInputs, TimingBudgetRequest
    from scenario_db.api.services.timing_budget import _sw_stats, analyze_timing_budget_request
    from scenario_db.sim.models import SimulationRunConfig
    from scenario_db.sim.timing_budget import TimingBudgetOptions

    base = _base_ref(db, req.base_params_ref, req.config_profile_ref)
    _params_row(db, base)
    rows, errors = [], []
    for m, synthetic in _measurements(db, req.project_ref, req.scenario_id, req.include_synthetic):
        use_sw = bool(req.measured_sw and _sw_stats(m))
        tb = TimingBudgetRequest(
            scenario_id=m.scenario_ref, variant_id=m.variant_ref, config_profile_ref=req.config_profile_ref,
            options=TimingBudgetOptions(statistic=req.statistic), config=SimulationRunConfig(power_params_ref=base),
            measured=MeasuredInputs(measurement_ref=str(m.id), sw=use_sw))
        try:
            rep = analyze_timing_budget_request(db, tb).report
        except Exception as exc:  # noqa: BLE001 - one variant must not stop the fit
            errors.append({"measurement_ref": m.id, "variant_id": m.variant_ref, "error": str(exc)[:300]})
            continue
        cmp_ = rep["measured_compare"]
        meas = {r["category"]: r["measurement_mw"] for r in cmp_["rows"]}
        p = rep["power"]
        rows.append({"measurement_ref": m.id, "scenario_id": m.scenario_ref, "variant_id": m.variant_ref, "synthetic": synthetic,
                     "measured_sw": use_sw, "verdict": rep["verdict"]["status"],
                     "predicted": {"cpu": p["cpu_mw"], "ip": p["hw_mw"], "bw": p["bw_mw"], "total": p["total_mw"]},
                     "measured": {**meas, "total": cmp_["total"]["measurement_mw"]}})
    factors = {c: _fit([(r["predicted"][c], r["measured"].get(c)) for r in rows]) for c in CATS}
    for c in CATS:
        f = factors[c]
        # recommend only a factor that actually explains the measurements better
        f["recommended"] = bool(f.get("k") and f["n"] >= 3 and not f.get("clamped") and (f.get("r2_after") or -1) >= 0.5
                                and f["mape_after_pct"] < f["mape_before_pct"])
    for r in rows:
        after = {c: (r["predicted"][c] * factors[c]["k"] if factors[c].get("k") else r["predicted"][c]) for c in CATS}
        r["after"] = {**{c: round(v, 2) for c, v in after.items()}, "total": round(sum(after.values()), 2)}
        mt = r["measured"].get("total")
        r["delta_pct_before"] = round(100 * (r["predicted"]["total"] - mt) / mt, 1) if mt else None
        r["delta_pct_after"] = round(100 * (r["after"]["total"] - mt) / mt, 1) if mt else None
    warnings = []
    synth = sum(1 for r in rows if r["synthetic"])
    if synth:
        warnings.append(f"합성(SYNTHETIC) 측정 {synth}건 포함 — 흐름 검증용이며 실제 계수 근거가 아님")
    for c in CATS:
        f = factors[c]
        if f.get("n", 0) < 3:
            warnings.append(f"{c}: 측정 {f.get('n', 0)}건 — 3건 미만은 계수 근거 부족")
        if f.get("k") and not f["recommended"] and f.get("n", 0) >= 3:
            warnings.append(f"{c}: 단일 배율로는 설명되지 않음 (R² {f.get('r2_after')}, MAPE {f['mape_before_pct']}→{f['mape_after_pct']}%) — "
                            "적용 비권장, 모델 구조(OPP·SW 부하·rail 귀속) 확인")
        if f.get("clamped"):
            warnings.append(f"{c}: k={f['k_raw']} 이 허용 범위 {K_RANGE} 밖 — 모델 구조 문제 가능 (경계값으로 제한)")
    return {"base_params_ref": base, "statistic": req.statistic, "measured_sw": req.measured_sw,
            "rows": rows, "errors": errors, "factors": factors, "warnings": warnings}


# ------------------------------------------------------------------- new params version
def _scale_cpu(cpu: dict[str, Any], k: float) -> None:
    def opps(items):
        for o in items or []:
            if o.get("mw_per_core") is not None:
                o["mw_per_core"] = round(o["mw_per_core"] * k, 4)

    for c in cpu.get("clusters") or []:
        if c.get("coeff_uw_per_mhz_v2") is not None:
            c["coeff_uw_per_mhz_v2"] = round(c["coeff_uw_per_mhz_v2"] * k, 6)
        opps(c.get("opps"))
        if c.get("leakage"):
            c["leakage"]["mw_per_core_at_ref"] = round(c["leakage"]["mw_per_core_at_ref"] * k, 4)
    dsu = cpu.get("dsu")
    if dsu:
        opps(dsu.get("opps"))
        if dsu.get("leakage"):
            dsu["leakage"]["mw_per_core_at_ref"] = round(dsu["leakage"]["mw_per_core_at_ref"] * k, 4)


def _scale_bw(bw: dict[str, Any], k: float) -> bool:
    touched = False
    for key in ("mw_per_gbps", "e_read_mw_per_gbps", "e_write_mw_per_gbps"):
        if bw.get(key) is not None:
            bw[key] = round(bw[key] * k, 4)
            touched = True
    for o in bw.get("mif_opps") or []:
        o["base_mw"] = round(float(o.get("base_mw") or 0.0) * k, 4)
        touched = True
    return touched


def create_calibrated_params(db: Session, req: Any, user: str | None = None) -> dict[str, Any]:
    """New draft ``power_model_params`` version = base x the accepted factors (+ fit lineage). Returns its ref and
    the YAML (the DB row is the working copy; commit the YAML to the authoring tree to keep it)."""
    from scenario_db.db.models.capability import PowerModelParams as Row
    from scenario_db.models.capability.power_model import PowerModelParams
    from scenario_db.sim.power_params import power_params_from_row

    base_row = _params_row(db, req.base_params_ref)
    base = power_params_from_row(base_row)
    doc = base.model_dump(mode="json", exclude_none=True)
    applied: dict[str, float] = {}
    for cat, k in req.factors.items():
        if cat not in CATS or k is None or abs(k - 1.0) < 1e-6:
            continue
        if not K_RANGE[0] <= k <= K_RANGE[1]:
            raise UnprocessableError(f"{cat} factor {k} outside {K_RANGE}")
        if cat == "cpu":
            if not (doc.get("cpu") or {}).get("clusters"):
                raise UnprocessableError("base params has no CPU clusters to scale")
            _scale_cpu(doc["cpu"], k)
        elif cat == "bw":
            if not _scale_bw(doc.setdefault("bw", {}), k):
                raise UnprocessableError("base params has no BW coefficients to scale (bw_model builtin)")
        else:
            cal = doc.setdefault("calibration", {})
            scale = dict(cal.get("ip_power_scale") or {})
            scale["*"] = round(float(scale.get("*", 1.0)) * k, 4)
            cal["ip_power_scale"] = scale
        applied[cat] = k
    if not applied:
        raise UnprocessableError("no factor to apply")
    version = (db.query(func.max(Row.version)).filter(Row.soc_ref == base_row.soc_ref).scalar() or 0) + 1
    new_id = re.sub(r"-v\d+$", f"-v{version}", base_row.id) if re.search(r"-v\d+$", base_row.id) else f"{base_row.id}-v{version}"
    if db.get(Row, new_id) is not None:
        new_id = f"{new_id}-cal"
    cal = doc.setdefault("calibration", {})
    cal["source_evidence"] = sorted(set(req.source_evidence))
    cal["fit"] = {"method": "least_squares_through_origin", "base_params_ref": base.params_ref, "statistic": req.statistic,
                  "measured_sw": req.measured_sw, "synthetic_rows": req.synthetic_rows,
                  "factors": {c: {"k": k, **{kk: vv for kk, vv in (req.fit_stats.get(c) or {}).items() if kk in ("n", "rmse_before_mw", "rmse_after_mw", "r2_after")}}
                              for c, k in applied.items()}}
    doc.update({"id": new_id, "version": version, "status": "draft",
                "description": req.description or f"{base.params_ref} x fit ({', '.join(f'{c} {k:g}' for c, k in applied.items())})",
                "notes": (f"Calibrated from {len(cal['source_evidence'])} measurements by {user or 'unknown'}; "
                          f"base {base.params_ref}." + (" SYNTHETIC rows included — flow check only." if req.synthetic_rows else ""))})
    params = PowerModelParams.model_validate(doc)
    text = yaml.safe_dump(params.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True)
    row = Row(id=new_id, schema_version=params.schema_version, soc_ref=str(params.soc_ref), version=version,
              status="draft", description=params.description,
              params=params.model_dump(mode="json", exclude_none=True,
                                       include={"ip_model", "ref_voltage_mv", "ref_fps", "ip_clock_power_fraction", "bw_model", "bw", "cpu", "calibration"}),
              notes=params.notes, yaml_sha256=hashlib.sha256(text.encode()).hexdigest())
    db.add(row)
    db.commit()
    return {"params_ref": params.params_ref, "id": new_id, "version": version, "applied": applied, "yaml": text,
            "params_hash": params.params_hash()}
