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
from scenario_db.db.models.exploration import ArchExplorationRun, Prediction
from scenario_db.exceptions import NotFoundError


def power_references(db: Session, project_ref: str) -> dict[str, Any]:
    """Per variant id: reference mW and where it came from (explicit value > previous project's prediction > measurement)."""
    policy = project_policy(db, project_ref)
    ref = policy.power_reference if policy else None
    out: dict[str, dict[str, Any]] = {}
    if ref is None:
        return {"policy": policy_view(policy), "tolerance_pct": None, "references": out}
    if ref.project_ref:
        for p in db.query(Prediction).filter(Prediction.project_ref == ref.project_ref, Prediction.status == "current").all():
            mw = ((p.metrics or {}).get("power") or {}).get("total_mw")
            if mw is not None:
                out.setdefault(p.variant_ref, {"mw": float(mw), "source": "prediction", "project_ref": ref.project_ref,
                                               "id": p.id, "at": _iso(p.created_at)})
        meas = (db.query(Evidence).filter(Evidence.kind == "evidence.measurement", Evidence.project_ref == ref.project_ref).all())
        meas.sort(key=lambda m: (not is_synthetic(m.provenance), _when(_iso(m.measured_at))), reverse=True)
        for m in meas:
            mw = _total(m.kpi).get("mean")
            if mw is not None and m.variant_ref not in out:
                out[m.variant_ref] = {"mw": float(mw), "source": "synthetic" if is_synthetic(m.provenance) else "measurement",
                                      "project_ref": ref.project_ref, "id": m.id, "at": _iso(m.measured_at)}
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


_REVIEW_COST = {"adopted": "IQ 승인 완료", "iq_eval": "IQ 평가 중", "rejected": "IQ 반려 — 사용 불가", "candidate": "IQ (option · 평가 필요)"}


def reduction_menu(v: dict[str, Any], current_mw: float, dvfs_rows: list[dict[str, Any]] | None = None,
                   review_of=None) -> list[dict[str, Any]]:
    """Levers that lower power, cheapest first: no-cost (DVFS level down that still meets fps) → IQ-approved options →
    lossy → options still to evaluate. ``review_of(key) -> {"status", ...}`` (EXP-06) attaches the stored IQ review;
    a rejected option stays listed but is not used by the plans."""
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
            review = review_of(m["key"]) if review_of else None
            status = (review or {}).get("status") or "candidate"
            items.append({"key": m["key"], "label": m["label"], "kind": "option", "feasible": status != "rejected",
                          "cost": _REVIEW_COST.get(status, _REVIEW_COST["candidate"]), "review": review,
                          "iq_status": status,
                          "delta_mw": round(m["mean_mw"], 2), "range_mw": [m["min_mw"], m["max_mw"]],
                          "always_beneficial": m.get("always_beneficial"), "exclusive": m.get("dimension") or m["key"]})

    def rank(x: dict[str, Any]) -> int:
        if x["kind"] == "dvfs":
            return 0
        if x["kind"] == "option" and x.get("iq_status") == "adopted":
            return 1
        return 2 if x["kind"] == "lossy" else 3
    items.sort(key=lambda x: (not x["feasible"], rank(x), x["delta_mw"]))
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
    chosen = [i for i in items if i["key"] in picked]
    return {"ask_pct": ask_pct, "need_mw": round(-need, 2), "picked": picked, "saving_mw": round(total, 2),
            "achieved": total <= -need + 1e-6, "iq_cost": any(i["kind"] != "dvfs" for i in chosen),
            # EXP-06: the plan needs no further IQ work when every IQ item in it is already adopted
            "iq_pending": [i["key"] for i in chosen if i["kind"] != "dvfs" and i.get("iq_status") != "adopted"]}


def approved_plan(items: list[dict[str, Any]], current_mw: float, ask_pct: float) -> dict[str, Any]:
    """Same greedy plan restricted to levers usable today: DVFS (fps kept) + IQ-adopted options."""
    usable = [i for i in items if i["kind"] == "dvfs" or i.get("iq_status") == "adopted"]
    return plan_for(usable, current_mw, ask_pct) | {"scope": "approved"}


_RES_RANK = {"HD": 0, "FHD": 1, "QHD": 2, "UHD": 3, "4K": 3, "8K": 4}
_TRADE_KEYS = ("fps", "resolution", "stabilization", "hdr", "power_saving_mode", "sensor_mode")
_OFF_WHEN_MISSING = {"stabilization": 0, "power_saving_mode": 0, "sensor_mode": "normal"}


def _camera(dc: dict[str, Any]) -> tuple[Any, Any]:
    """Same camera setup = same sensor place and the same DVFS scenario family (REAR_SINGLE / REAR_DUAL / FRONT_SINGLE)."""
    sn = str(dc.get("dvfs_sn") or "")
    fam = "_".join(sn.removeprefix("IS_DVFS_SN_").split("_")[:2]) if sn else None
    return dc.get("sensor_place"), fam


def _trade_diffs(me: dict[str, Any], dc: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Changes from the watched variant to a sibling; None = not a performance trade-down (other camera, higher
    fps / resolution, SDR -> HDR)."""
    if _camera(me) != _camera(dc):
        return None
    try:
        if float(dc.get("fps") or 0) > float(me.get("fps") or 0):
            return None
    except (TypeError, ValueError):
        return None
    if _RES_RANK.get(str(dc.get("resolution")), -1) > _RES_RANK.get(str(me.get("resolution")), 99):
        return None
    if str(me.get("hdr") or "SDR") == "SDR" and dc.get("hdr") not in (None, "SDR"):
        return None
    diffs = []
    for k in _TRADE_KEYS:
        a, b = me.get(k, _OFF_WHEN_MISSING.get(k)), dc.get(k, _OFF_WHEN_MISSING.get(k))
        a = _OFF_WHEN_MISSING.get(k) if a is None else a
        b = _OFF_WHEN_MISSING.get(k) if b is None else b
        if a is None or b is None or a == b:
            continue
        if k in ("stabilization", "power_saving_mode") and a == 0:
            return None  # turning a feature on is not a trade-down
        diffs.append({"key": k, "from": a, "to": b})
    return diffs or None


def performance_trades(db: Session, scenario_id: str, variant_id: str, current_mw: float, limit: int = 6) -> list[dict[str, Any]]:
    """EXP-04: sibling variants of the same scenario that drop performance (fps / resolution / stabilization ...) and
    their registered power vs the watched case — what the customer gives up for each mW. Higher fps or resolution
    is not a trade-down and is skipped."""
    from scenario_db.db.models.definition import ScenarioVariant

    variants = {v.id: (v.design_conditions or {}) for v in db.query(ScenarioVariant).filter_by(scenario_id=scenario_id).all()}
    me = variants.get(variant_id)
    if me is None:
        return []
    preds = {p.variant_ref: p for p in db.query(Prediction).filter_by(scenario_ref=scenario_id, status="current").all()}
    out = []
    for vid, dc in variants.items():
        p = preds.get(vid)
        mw = ((p.metrics or {}).get("power") or {}).get("total_mw") if p is not None else None
        if vid == variant_id or mw is None or float(mw) >= current_mw - 0.5:
            continue
        diffs = _trade_diffs(me, dc)
        if not diffs:
            continue
        out.append({"variant_id": vid, "total_mw": round(float(mw), 2), "delta_mw": round(float(mw) - current_mw, 2),
                    "delta_pct": round(100.0 * (float(mw) - current_mw) / current_mw, 1) if current_mw else None,
                    "changes": diffs, "verdict": (p.metrics or {}).get("verdict"), "prediction_id": p.id})
    # one row per kind of change (UHD30 SDR / recursive / portrait give the same trade): keep the lowest power
    best: dict[str, dict[str, Any]] = {}
    for t in sorted(out, key=lambda x: x["delta_mw"]):
        sig = "|".join(f"{c['key']}={c['to']}" for c in t["changes"])
        if sig in best:
            best[sig].setdefault("also", []).append(t["variant_id"])
        else:
            best[sig] = t
    rows = sorted(best.values(), key=lambda x: (len(x["changes"]), x["delta_mw"]))
    return rows[:limit]


def thermal_watch(db: Session, project_ref: str, *, dvfs_whatif=None) -> dict[str, Any]:
    """Per watch-list variant: current prediction, reference judgement, reduction menu and 10 / 20 % plans.

    ``dvfs_whatif(scenario_id, variant_id) -> rows`` supplies DVFS level-down rows (timing-budget what-if); omitted =
    no DVFS levers (tests, or when the timing analysis fails).
    """
    policy = project_policy(db, project_ref)
    if policy is None:
        raise NotFoundError(f"project has no review_policy: {project_ref}")
    refs = power_references(db, project_ref)
    out = []
    for w in policy.thermal_watch:
        pred = db.query(Prediction).filter_by(scenario_ref=w.scenario_ref, variant_ref=w.variant_ref, status="current").one_or_none()
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
            "menu": [], "plans": [], "approved_plans": [], "trades": [], "notes": [],
        }
        if v is None or current is None:
            row["notes"].append("조합 탐색 결과가 없습니다 — 이 variant를 포함해 조합 탐색(power option 켬)을 실행하세요")
        else:
            if not (v.get("power_options") or {}).get("marginal"):
                row["notes"].append("power option 단독 효과가 없는 run — power option을 켜고 다시 실행하면 option 항목이 채워집니다")
            dv_rows = None
            if dvfs_whatif is not None:
                try:
                    dv_rows = dvfs_whatif(w.scenario_ref, w.variant_ref)
                except Exception as exc:  # noqa: BLE001 - the menu still works without DVFS levers
                    row["notes"].append(f"DVFS level what-if 실패: {str(exc)[:160]}")
            reviews = _reviews(db, w.scenario_ref)
            row["menu"] = reduction_menu(v, float(current), dv_rows,
                                         review_of=lambda k, vid=w.variant_ref: _review_state(reviews, vid, k))
            row["plans"] = [plan_for(row["menu"], float(current), p) for p in w.reduction_pct]
            row["approved_plans"] = [approved_plan(row["menu"], float(current), p) for p in w.reduction_pct]
            row["trades"] = performance_trades(db, w.scenario_ref, w.variant_ref, float(current))
            if rec_lossy and keep:
                row["notes"].append(f"등록 예측 {registered:.0f} mW는 lossy 압축 포함 (IQ 평가 전제) — 기준은 화질 유지 최적 {current:.0f} mW")
            if any(not i["feasible"] for i in row["menu"] if i["kind"] == "dvfs") and not any(i["feasible"] for i in row["menu"] if i["kind"] == "dvfs"):
                row["notes"].append("IP clock은 이미 fps를 만족하는 최소 level — 내리면 fps drop")
            short = [p for p in row["plans"] if not p["achieved"]]
            if short:
                row["notes"].append(f"{short[0]['ask_pct']:.0f}% 요청은 IQ 항목으로도 부족 (최대 {short[0]['saving_mw']:.0f} mW) — "
                                    "해상도·fps·EIS 등 성능 조건 변경(아래 성능 trade 후보) 검토 필요")
        out.append(row)
    return {"project_ref": project_ref, "policy": refs["policy"], "items": out}


def _reviews(db: Session, scenario_id: str) -> dict[tuple[str, str], Any]:
    from scenario_db.db.models.exploration import PowerOptionReview

    return {(r.variant_ref, r.option_key): r for r in db.query(PowerOptionReview).filter_by(scenario_ref=scenario_id).all()}


def _review_state(reviews: dict[tuple[str, str], Any], variant_id: str, key: str) -> dict[str, Any]:
    from scenario_db.api.services.arch_exploration import item_status

    return item_status(reviews, variant_id, key)


def battery_of(db: Session, config_profile_ref: str | None) -> dict[str, Any]:
    """Vbat / PMIC efficiency used for mA@Vbat (sim config profile run_config; default 4.0 V · 0.85)."""
    from scenario_db.db.models.capability import SimConfigProfile

    row = db.get(SimConfigProfile, config_profile_ref) if config_profile_ref else None
    rc = (row.run_config or {}) if row is not None else {}
    vbat, eff = rc.get("vbat") or 4.0, rc.get("pmic_efficiency") or 0.85
    return {"vbat": float(vbat), "pmic_efficiency": float(eff), "source": config_profile_ref if row is not None and (rc.get("vbat") or rc.get("pmic_efficiency")) else "default"}


def report_context(db: Session, project_ref: str | None, config_profile_ref: str | None,
                   predictions: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """Frozen with a report (RPT-03): review policy, battery conversion and each variant's previous-project judgement,
    so the report's mA and target verdicts do not move when the project settings change later."""
    bat = battery_of(db, config_profile_ref)
    refs = power_references(db, project_ref) if project_ref else {"policy": policy_view(None), "tolerance_pct": None, "references": {}}
    rows = []
    for (sid, vid), pred in predictions.items():
        mw = (((pred or {}).get("metrics") or {}).get("power") or {}).get("total_mw")
        j = judge_power(mw, refs["references"].get(vid), refs["tolerance_pct"])
        rows.append({"scenario_id": sid, "variant_id": vid, "total_mw": mw,
                     "ma": round(mw / bat["vbat"] / bat["pmic_efficiency"], 1) if mw is not None else None,
                     "throughput_model": ((pred or {}).get("metrics") or {}).get("throughput_model") or "stage",
                     "reference": j})
    return {"policy": refs["policy"], "battery": bat, "rows": rows}
