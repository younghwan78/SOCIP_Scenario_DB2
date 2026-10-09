"""Customer-target review: power reference ("similar to or below the previous project") and the thermal watch list.

Rules (project ``globals.review_policy``):
- fps drop is never allowed — timing ``fail`` / interval miss stays a high risk on the page.
- current power vs the previous project's value for the same variant: <= ref ok, <= ref x (1 + tol) similar, else over.
- thermal-watch variants (e.g. UHD120 Pro video, UHD portrait): a pre-computed reduction menu — what each lever saves
  (mW / mA), what it costs (none / IQ / latency), and which levers reach a 10 / 20 % ask.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, literal, literal_column
from sqlalchemy.orm import Session

from scenario_db.api.services.calibration import _iso, _total, _when, is_synthetic
from scenario_db.api.services.review_policy import policy_view, project_policy
from scenario_db.db.models.evidence import Evidence
from scenario_db.db.models.definition import Scenario, ScenarioVariant
from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
from scenario_db.exceptions import NotFoundError, UnprocessableError


def power_references(db: Session, project_ref: str) -> dict[str, Any]:
    """Per variant id: reference mW and where it came from (explicit value > previous project's prediction > measurement)."""
    policy = project_policy(db, project_ref)
    ref = policy.power_reference if policy else None
    out: dict[str, dict[str, Any]] = {}
    if ref is None:
        return {"policy": policy_view(policy), "tolerance_pct": None, "references": out}
    if ref.project_ref:
        scopes: dict[str, set[str]] = {}
        for p in db.query(Prediction).filter(Prediction.project_ref == ref.project_ref, Prediction.status == "current").all():
            mw = ((p.metrics or {}).get("power") or {}).get("total_mw")
            if mw is not None:
                scopes.setdefault(p.variant_ref, set()).add(p.scenario_ref)
                out.setdefault(p.variant_ref, {"mw": float(mw), "source": "prediction", "project_ref": ref.project_ref,
                                               "id": p.id, "at": _iso(p.created_at)})
        meas = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.project_ref == ref.project_ref).all())
        meas.sort(key=lambda m: (not is_synthetic(m.provenance), _when(_iso(m.measured_at))), reverse=True)
        for m in meas:
            mw = _total(m.kpi).get("mean")
            if mw is not None:
                scopes.setdefault(m.variant_ref, set()).add(m.scenario_ref)
            if mw is not None and m.variant_ref not in out:
                out[m.variant_ref] = {"mw": float(mw), "source": "synthetic" if is_synthetic(m.provenance) else "measurement",
                                      "project_ref": ref.project_ref, "id": m.id, "at": _iso(m.measured_at)}
        # Variant IDs are scenario-local. An ambiguous previous-project ID is not a usable reference.
        out = {vid: value for vid, value in out.items() if len(scopes.get(vid, set())) == 1}
    for vid, mw in ref.values_mw.items():
        out[vid] = {"mw": float(mw), "source": "explicit", "project_ref": ref.project_ref, "id": None, "at": None,
                    "note": ref.source_note}
    return {"policy": policy_view(policy), "tolerance_pct": ref.tolerance_pct, "references": out}


def judge_power(current_mw: float | None, reference: dict[str, Any] | None, tolerance_pct: float | None) -> dict[str, Any] | None:
    if current_mw is None or not reference:
        return None
    ref_mw = reference["mw"]
    delta = current_mw - ref_mw
    pct = 100.0 * delta / ref_mw if ref_mw else None
    tol = tolerance_pct or 0.0
    status = "ok" if delta <= 0 else "similar" if pct is not None and pct <= tol else "over"
    return {"reference_mw": round(ref_mw, 2), "delta_mw": round(delta, 2), "delta_pct": round(pct, 2) if pct is not None else None,
            "status": status, "source": reference["source"]}


def _run_variant(db: Session, run_id: str, scenario_id: str, variant_id: str) -> dict[str, Any] | None:
    R = ArchExplorationRun
    row = db.query(func.jsonb_path_query_first(
        R.variants, literal_column("'$[*] ? (@.scenario_id == $s && @.variant_id == $v)'::jsonpath"),
        func.jsonb_build_object(literal("s"), scenario_id, literal("v"), variant_id))).filter(R.id == run_id).scalar()
    return row


def _latest_run_with(db: Session, project_ref: str, scenario_id: str, variant_id: str) -> str | None:
    R = ArchExplorationRun
    for run_id, in db.query(R.id).filter(R.project_ref == project_ref).order_by(R.created_at.desc()).limit(20):
        if _run_variant(db, run_id, scenario_id, variant_id) is not None:
            return run_id
    return None


def reduction_menu(v: dict[str, Any], current_mw: float, dvfs_rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Levers that lower power, cheapest first: no-cost (DVFS level down that still meets fps) → IQ (lossy, options)."""
    items: list[dict[str, Any]] = []
    for r in dvfs_rows or []:
        if r.get("shift", 0) >= 0 or r.get("error") or (r.get("delta_mw") or 0) >= -0.05:
            continue
        ok = r.get("verdict") in ("ok", "clock_up")
        items.append({"key": f"dvfs:{r['domain']}:L{r['level']}", "label": f"{r['domain']} L{r['level']} ({r['mhz']:.0f} MHz)",
                      "kind": "dvfs", "feasible": ok,
                      "cost": "없음 (fps 유지 · SW 여유 감소)" if ok else f"fps drop — {(r.get('reasons') or ['timing fail'])[0]}",
                      "delta_mw": round(r["delta_mw"], 2), "latency_ms": (r.get("latency_ms") or {}).get("video_ms"),
                      "exclusive": f"dvfs:{r['domain']}"})
    tiers = v.get("tiers") or {}
    gain = tiers.get("trade_gain")
    if gain and gain.get("delta_mw", 0) < -0.05:
        bufs = ((tiers.get("trade") or {}).get("best") or {}).get("compression") or []
        items.append({"key": "lossy", "label": f"lossy compression ({', '.join(bufs) or 'buffer'})", "kind": "lossy", "feasible": True,
                      "cost": "IQ (lossy 압축 · 평가 필요)", "delta_mw": round(gain["delta_mw"], 2), "exclusive": "lossy"})
    for m in (v.get("power_options") or {}).get("marginal") or []:
        if m.get("mean_mw", 0) < -0.05:
            items.append({"key": m["key"], "label": m["label"], "kind": "option", "feasible": True, "cost": "IQ (option · 평가 필요)",
                          "delta_mw": round(m["mean_mw"], 2), "range_mw": [m["min_mw"], m["max_mw"]],
                          "always_beneficial": m.get("always_beneficial"), "exclusive": m.get("dimension") or m["key"]})
    rank = {"dvfs": 0, "lossy": 1, "option": 2}
    items.sort(key=lambda x: (not x["feasible"], rank[x["kind"]], x["delta_mw"]))
    return items


def plan_for(items: list[dict[str, Any]], current_mw: float, ask_pct: float) -> dict[str, Any]:
    """Greedy: cheapest kind first, biggest saving within a kind; one item per exclusive group (one level per domain)."""
    need = current_mw * ask_pct / 100.0
    used: set[str] = set()
    picked, total = [], 0.0
    for it in items:
        if total <= -need:
            break
        if not it["feasible"]:
            continue
        if it["exclusive"] in used:
            continue
        used.add(it["exclusive"])
        picked.append(it["key"])
        total += it["delta_mw"]
    return {"ask_pct": ask_pct, "need_mw": round(-need, 2), "picked": picked, "saving_mw": round(total, 2),
            "achieved": total <= -need + 1e-6, "iq_cost": any(i["kind"] != "dvfs" for i in items if i["key"] in picked)}


def thermal_watch(db: Session, project_ref: str, *, dvfs_whatif=None) -> dict[str, Any]:
    """Per watch-list variant: current prediction, reference judgement, reduction menu and 10 / 20 % plans.

    ``dvfs_whatif(scenario_id, variant_id) -> {base, rows}`` supplies DVFS level-down rows with their baseline; omitted =
    no DVFS levers (tests, or when the timing analysis fails).
    """
    policy = project_policy(db, project_ref)
    if policy is None:
        raise NotFoundError(f"project has no review_policy: {project_ref}")
    refs = power_references(db, project_ref)
    out = []
    for w in policy.thermal_watch:
        scenario = db.get(Scenario, w.scenario_ref)
        if scenario is None or scenario.project_ref != project_ref:
            raise UnprocessableError("thermal-watch scenario must belong to the selected project")
        if db.get(ScenarioVariant, (w.scenario_ref, w.variant_ref)) is None:
            raise UnprocessableError("thermal-watch variant does not exist in the selected scenario")
        pred = db.query(Prediction).filter_by(project_ref=project_ref, scenario_ref=w.scenario_ref,
                                             variant_ref=w.variant_ref, status="current").one_or_none()
        run_id = pred.exploration_run_ref if pred is not None else _latest_run_with(db, project_ref, w.scenario_ref, w.variant_ref)
        v = _run_variant(db, run_id, w.scenario_ref, w.variant_ref) if run_id else None
        registered = ((pred.metrics or {}).get("power") or {}).get("total_mw") if pred is not None else \
            ((v or {}).get("recommended") or {}).get("total_mw")
        keep = (((v or {}).get("tiers") or {}).get("keep") or {}).get("best")
        # baseline = IQ/performance-keeping optimum: a registered min-power case with lossy compression already
        # spends an IQ lever, so reductions are counted from the case that needs no IQ evaluation
        current = keep["total_mw"] if keep else registered
        # registered below the IQ-keeping optimum = the registered case already spends lossy compression
        rec_lossy = bool(keep and registered is not None and registered < keep["total_mw"] - 0.5)
        row: dict[str, Any] = {
            "scenario_id": w.scenario_ref, "variant_id": w.variant_ref, "label": w.label or w.variant_ref, "note": w.note,
            "prediction_id": pred.id if pred is not None else None, "run_id": run_id, "current_mw": current,
            "baseline": "iq_keep" if keep else "registered", "registered_mw": registered, "registered_lossy": rec_lossy,
            "throughput_model": ((pred.metrics or {}).get("throughput_model") if pred is not None else (v or {}).get("throughput_model")) or "stage",
            "verdict": (pred.metrics or {}).get("verdict") if pred is not None else ((v or {}).get("recommended") or {}).get("verdict"),
            "reference": judge_power(current, refs["references"].get(w.variant_ref), refs["tolerance_pct"]),
            "menu": [], "plans": [], "notes": [],
        }
        if v is None or current is None:
            row["notes"].append("조합 탐색 결과가 없습니다 — 이 variant를 포함해 조합 탐색(power option 켬)을 실행하세요")
        else:
            if not (v.get("power_options") or {}).get("marginal"):
                row["notes"].append("power option 단독 효과가 없는 run — power option을 켜고 다시 실행하면 option 항목이 채워집니다")
            dv_rows = None
            if dvfs_whatif is not None:
                try:
                    dvfs = dvfs_whatif(w.scenario_ref, w.variant_ref)
                    base_mw = (dvfs.get("base") or {}).get("total_mw")
                    if base_mw is not None and abs(float(base_mw) - float(current)) <= 0.5:
                        dv_rows = dvfs["rows"]
                    else:
                        row["notes"].append("DVFS 기준 power가 화질 유지 기준과 달라 절감량 합산에서 제외 — 동일 조건으로 재계산 필요")
                except Exception as exc:  # noqa: BLE001 - the menu still works without DVFS levers
                    row["notes"].append(f"DVFS level what-if 실패: {str(exc)[:160]}")
            row["menu"] = reduction_menu(v, float(current), dv_rows)
            row["plans"] = [plan_for(row["menu"], float(current), p) for p in w.reduction_pct]
            if rec_lossy and keep:
                row["notes"].append(f"등록 예측 {registered:.0f} mW는 lossy 압축 포함 (IQ 평가 전제) — 기준은 화질 유지 최적 {current:.0f} mW")
            if any(not i["feasible"] for i in row["menu"] if i["kind"] == "dvfs") and not any(i["feasible"] for i in row["menu"] if i["kind"] == "dvfs"):
                row["notes"].append("IP clock은 이미 fps를 만족하는 최소 level — 내리면 fps drop")
            short = [p for p in row["plans"] if not p["achieved"]]
            if short:
                row["notes"].append(f"{short[0]['ask_pct']:.0f}% 요청은 IQ 항목으로도 부족 (최대 {short[0]['saving_mw']:.0f} mW) — "
                                    "해상도·fps·EIS 등 성능 조건 변경(다른 variant) 검토 필요")
        out.append(row)
    return {"project_ref": project_ref, "policy": refs["policy"], "items": out}
