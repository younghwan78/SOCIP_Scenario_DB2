"""Review verdicts and the one-page summary of a project report.

REF-05  previous-project verdict from the registered prediction, its exploration range, the bias-corrected
        prediction and silicon measurement (ok / similar / conditional / over / na) + prediction-vs-silicon flip
RISK-01 validity of an fps miss: confirmed · model_limit (outside the model) · input_unverified (assumed inputs)
COV-03  KPI scoreboard (policy ``kpi`` list; default = thermal watch + previous-project reference variants)
RISK-04 risk drivers — where to look first
Lever ladder (power-saving order used for actions and mitigations):
        ① optimal clock → ② compression → ③ SW optimization → ④ IQ-degrading options (last resort)

Pure functions over the frozen snapshot: a regenerated report states the same verdicts for the same numbers.
"""

from __future__ import annotations

from typing import Any

HIGH_FPS = 120.0          # STANDING_LIMITS: NRT batch processing is not modelled at or above this rate
BIAS_MIN_N = 5            # a total-power bias is applied only when it is systematic and backed by enough captures
LOW_MARGIN_PCT = 10.0

LADDER = {
    1: ("clock", "① Clock 최적화"),
    2: ("compression", "② Compression"),
    3: ("sw", "③ SW 최적화"),
    4: ("iq_trade", "④ 화질 열화 option (최후 수단)"),
}
LADDER_TEXT = "① clock 최적화(DVFS level · RT 최소 clock) → ② compression(lossless · LLC → lossy) → ③ SW 최적화(task · CPU 배치) → ④ 화질 열화 option은 마지막(IQ 평가)"

STATE_LABEL = {"ok": "이하", "similar": "유사", "conditional": "조건부", "over": "초과", "na": "판정 불가", "uncovered": "미탐색"}
VALIDITY_LABEL = {"confirmed": "확정", "model_limit": "모델 한계", "input_unverified": "입력 미확정"}

# UX-02: internal keys → words a reader recognises (the key stays in parentheses where it helps a reviewer)
GLOSSARY = [
    ("프레임 병렬 처리 기준 (pipelined)", "stage 사이 M2M buffer로 분리 — fps는 최종 출력 간격으로 판정, 한 stage가 1 frame을 넘으면 latency만 증가"),
    ("stage 기준 (stage)", "모든 stage가 1 frame 안에 끝나야 fps 충족"),
    ("화질 유지 조합 (iq_keep)", "lossy 압축 · assumed ratio · 화질 열화 option 없이 가장 낮은 power 조합 — 등록 기본값"),
    ("최저 전력 조합 (min_power)", "화질 영향 항목 포함 최저 power — IQ 평가 전제"),
    ("탐색 범위", "조합 탐색 분포 min~max (SW 통계 mean/max × SW 증가 × DVFS +1 level)"),
    ("보정 예측", "예측 ÷ (1 + 실측 대조 total median 오차) — 오차가 체계적(같은 부호 다수)이고 대조 5건 이상일 때만"),
    ("SW margin", "frame 주기 대비 SW 여유 % — stage 기준은 (주기 − stage SW − HW), pipelined는 (주기 − 최장 SW task 또는 같은 CPU의 SW 합). "
                  "pipelined에서 stage chain이 주기를 넘는 것은 '동시 frame' 수(latency)로 따로 표시"),
    ("동시 frame", "stage chain(HW + SW)이 frame 주기 몇 개에 걸치는지 — pipelined에서 fps는 유지되고 buffer · latency만 늘어남"),
    ("모델 lineage", "예측을 만든 계산 모델 (power model · version · BW model · 계수 · clock 기준) — 다르면 숫자 차이가 설계 차이가 아님"),
    ("post_irta", "NRT 후단 SW task (IRTA 후처리) — 현재 SW 여유 부족의 공통 병목"),
    ("SAMPLE", "사외 검증용 가상 값 — 사내 table · 실측으로 교체 대상"),
    ("부하 등급", "variant 정의의 severity (light · medium · heavy · critical) — risk 심각도와 별개"),
]


def _f(v: Any, d: int = 0) -> str:
    try:
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return "—"


def short(v: str) -> str:
    return str(v).replace("cam-rec-", "")


def _pct(x: float | None, ref: float | None) -> float | None:
    if x is None or not ref:
        return None
    return round(100.0 * (float(x) - float(ref)) / float(ref), 2)


def _keymap(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r.get("scenario_id"), r["variant_id"]): r for r in rows if r.get("variant_id")}


# ------------------------------------------------------------------- RISK-01 fps validity
def fps_validity(row: dict[str, Any]) -> tuple[str, str]:
    """(validity, why) of one fps miss."""
    inputs = row.get("inputs") or {}
    codes = {e.get("code") for e in row.get("reasons_explained") or []}
    fps = float(row.get("fps") or 0)
    # Batch modelling can explain NRT/SW interval failures, not an independent RT,
    # verification or hardware-clock failure. Keep those failures actionable.
    independent = codes & {"rt_budget", "verify", "constraint", "no_case", "model", "other"}
    if fps >= HIGH_FPS and codes & {"sw_budget", "interval"} and not independent:
        return "model_limit", "120 fps 이상 NRT batch · sensor 내부 buffer 미모델 (1 frame = 1 period 가정)"
    if str(inputs.get("sensor_support") or "").startswith("unverified"):
        return "input_unverified", f"sensor 지원 미확인 ({inputs['sensor_support']})"
    if inputs.get("sw_timing_source") == "assumed" and codes & {"sw_budget", "interval"} and not independent:
        return "input_unverified", "SW timing 가정값 (측정 기반 아님)"
    return "confirmed", ""


# ------------------------------------------------------------------- REF-05 power verdicts
def _bias(snap: dict[str, Any]) -> dict[str, Any] | None:
    b = ((snap.get("model") or {}).get("bias") or {}).get("total") or {}
    if b.get("median") is None or float(b["median"]) <= -100 or (b.get("n") or 0) < BIAS_MIN_N or b.get("verdict") not in ("bias", "model_common"):
        return None
    return {"median": float(b["median"]), "n": b.get("n"), "same_sign_pct": b.get("same_sign_pct")}


def power_verdicts(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per variant that has a previous-project reference (references frozen in the snapshot)."""
    refs: dict[str, dict[str, Any]] = snap.get("references") or {}
    if not refs:
        return []
    tol = float(((snap.get("criteria") or {}).get("power") or {}).get("tolerance_pct") or 0.0)
    rows = snap.get("scenarios") or []
    by_vid: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_vid.setdefault(r["variant_id"], []).append(r)
    cal = _keymap(snap.get("calibration") or [])
    bias = _bias(snap)
    out = []
    for vid, ref in sorted(refs.items()):
        R = float(ref["mw"])
        cands = by_vid.get(vid) or []
        if len(cands) != 1:
            out.append({"variant_id": vid, "scenario_id": None, "ref_mw": R, "ref_source": ref.get("source"), "state": "uncovered",
                        "registered": False, "flip": False, "why": "탐색 결과 없음" if not cands else "같은 id가 여러 scenario에 있음"})
            continue
        r = cands[0]
        P = (r.get("power") or {}).get("total_mw") if r.get("spec_ok") else None
        dist = (r.get("distribution") or {}).get("total_mw") or {}
        band = [dist.get("min"), dist.get("max")] if r.get("spec_ok") and dist.get("min") is not None else None
        c = cal.get((r["scenario_id"], vid)) or {}
        physical = c.get("origin") == "physical_capture" if c.get("origin") else (bool(c) and not c.get("synthetic"))
        M = c.get("measured_mw") if c else None
        corr = round(float(P) / (1 + bias["median"] / 100.0), 2) if bias and P is not None else None
        p_pct, m_pct = _pct(P, R), _pct(M, R)
        primary = m_pct if physical and M is not None else p_pct
        hi_pcts = [x for x in (_pct(band[1], R) if band else None, _pct(corr, R), None if physical else m_pct) if x is not None]
        if primary is None:
            state = "na"
        elif primary > tol:
            state = "over"
        elif any(x > tol for x in hi_pcts):
            state = "conditional"
        elif primary > 0:
            state = "similar"
        else:
            state = "ok"
        flip = bool(physical and p_pct is not None and m_pct is not None and (p_pct > tol) != (m_pct > tol))
        reasons = []
        if flip:
            reasons.append(f"예측 {p_pct:+.1f}% ↔ 실측 {m_pct:+.1f}%")
        if state == "conditional":
            if band and (_pct(band[1], R) or 0) > tol:
                reasons.append(f"탐색 범위 상단 {_pct(band[1], R):+.1f}%")
            if corr is not None and (_pct(corr, R) or 0) > tol:
                reasons.append(f"보정 예측 {_pct(corr, R):+.1f}%")
            if M is not None and not physical and (m_pct or 0) > tol:
                reasons.append(f"합성 실측 {m_pct:+.1f}%")
        if not r.get("prediction_id"):
            reasons.append("미등록 — 탐색값" if P is not None else "미등록 — 비교 가능한 예측 없음")
        out.append({
            "scenario_id": r["scenario_id"], "variant_id": vid, "ref_mw": R, "ref_source": ref.get("source"),
            "pred_mw": P, "pred_pct": p_pct, "registered": bool(r.get("prediction_id")),
            "band_mw": band, "band_pct": [_pct(band[0], R), _pct(band[1], R)] if band else None,
            "corr_mw": corr, "corr_pct": _pct(corr, R), "bias_pct": bias["median"] if bias else None,
            "meas_mw": M, "meas_pct": m_pct, "meas_origin": (c.get("origin") or ("synthetic" if c.get("synthetic") else None)) if c else None,
            "basis": "measurement" if physical and M is not None else "prediction",
            "state": state, "flip": flip, "iq_conditional": bool(r.get("lossy") or r.get("assumed_ratio")),
            "tolerance_pct": tol, "why": " · ".join(reasons),
            **compare_previous(r, ref),
        })
    return out


_RES_RANK = {"HD": 0, "FHD": 1, "QHD": 2, "UHD": 3, "4K": 3, "8K": 4}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare_previous(row: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    """REF-02/03/04 against the previous project's same variant: condition differences, spec upgrade,
    CPU / IP / BW decomposition of the power change and the video latency change (frames)."""
    out: dict[str, Any] = {"prev_variant": ref.get("prev_variant"), "cond_diff": None, "spec_up": [], "decomp": None,
                           "latency_delta_frames": None}
    prev_c, cur_c = ref.get("conditions"), row.get("conditions") or {}
    if prev_c is not None:
        diff = [{"key": k, "prev": prev_c.get(k), "cur": cur_c.get(k)} for k in sorted(set(prev_c) | set(cur_c))
                if k in prev_c and prev_c.get(k) != cur_c.get(k)]
        out["cond_diff"] = diff
        for d in diff:
            if d["key"] == "fps" and (_num(d["cur"]) or 0) > (_num(d["prev"]) or 0):
                out["spec_up"].append(f"fps {d['prev']}→{d['cur']}")
            elif d["key"] == "resolution" and _RES_RANK.get(str(d["cur"]), -1) > _RES_RANK.get(str(d["prev"]), 99):
                out["spec_up"].append(f"해상도 {d['prev']}→{d['cur']}")
            elif d["key"] == "hdr" and str(d["prev"] or "SDR") == "SDR" and str(d["cur"] or "SDR") != "SDR":
                out["spec_up"].append(f"{d['prev']}→{d['cur']}")
    sp, pw = ref.get("split") or {}, row.get("power") or {}
    if sp and row.get("spec_ok") and pw.get("total_mw") is not None:
        parts = {"CPU": (pw.get("cpu_mw"), sp.get("cpu_mw")), "IP": (pw.get("hw_mw"), sp.get("ip_mw")), "BW": (pw.get("bw_mw"), sp.get("bw_mw"))}
        dec = {k: round(float(a) - float(b), 1) for k, (a, b) in parts.items() if a is not None and b is not None}
        if dec:
            known = sum(dec.values())
            # the reference may be a measurement while the split comes from the previous prediction
            dec["기준 차이"] = round(float(pw["total_mw"]) - float(ref["mw"]) - known, 1)
            out["decomp"] = dec
    lat_prev, lat_cur = ref.get("latency_frames"), (row.get("latency") or {}).get("video_frames")
    if lat_prev is not None and lat_cur is not None:
        out["latency_delta_frames"] = round(float(lat_cur) - float(lat_prev), 2)
    return out


def growth_budget_state(sw: dict[str, Any], budget: float | None) -> str:
    """A tolerance at the largest tested growth is a lower bound, not a known failure above it."""
    tolerance, tested = sw.get("growth_tolerance"), sw.get("growth_tested_max")
    if budget is None or tolerance is None:
        return "unknown"
    if float(tolerance) >= float(budget) - 1e-6:
        return "ok"
    if tested is not None and float(tolerance) >= float(tested) - 1e-6:
        return "unverified"
    return "short"


# ------------------------------------------------------------------- COV-03 KPI scoreboard
def kpi_list(snap: dict[str, Any]) -> list[dict[str, Any]]:
    policy = (snap.get("review_context") or {}).get("policy") or {}
    declared = policy.get("kpi") or []
    if declared:
        return [{"variant_ref": k["variant_ref"], "scenario_ref": k.get("scenario_ref"), "label": k.get("label") or short(k["variant_ref"]),
                 "tier": k.get("tier") or "base"} for k in declared]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str]] = set()
    for w in policy.get("thermal_watch") or []:
        key = (w.get("scenario_ref"), w["variant_ref"])
        if key not in seen:
            seen.add(key)
            out.append({"variant_ref": w["variant_ref"], "scenario_ref": w.get("scenario_ref"), "label": w.get("label") or short(w["variant_ref"]),
                        "tier": "thermal"})
    for vid in sorted(snap.get("references") or {}):
        if not any(v == vid for _, v in seen):
            seen.add((None, vid))
            out.append({"variant_ref": vid, "scenario_ref": None, "label": short(vid), "tier": "base"})
    return out


def _find(rows: list[dict[str, Any]], vid: str, sid: str | None) -> dict[str, Any] | None:
    c = [r for r in rows if r["variant_id"] == vid and (sid is None or r["scenario_id"] == sid)]
    return c[0] if len(c) == 1 else None


_RANK = {"fail": 0, "org": 1, "warn": 2, "mute": 3, "ok": 4}


def scoreboard(snap: dict[str, Any], verdicts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rows = snap.get("scenarios") or []
    vmap = {v["variant_id"]: v for v in (verdicts if verdicts is not None else power_verdicts(snap))}
    opts = _keymap(snap.get("power_options") or [])
    throughput = (((snap.get("review_context") or {}).get("policy") or {}).get("throughput_model")) or "stage"
    out = []
    for k in kpi_list(snap):
        r = _find(rows, k["variant_ref"], k.get("scenario_ref"))
        v = vmap.get(k["variant_ref"])
        if r is None:
            out.append(k | {"covered": False, "fps": {"state": "uncovered", "label": "미탐색", "cls": "mute"},
                            "power": None, "verdict": v, "sw_margin_pct": None, "iq": None,
                            "overall": {"cls": "fail", "label": "미커버"}})
            continue
        if r["spec_ok"]:
            n = (r.get("sw") or {}).get("in_flight")
            # engine ≥ 15 records the margin basis (pipelined margin = per thread, frames in flight from the chain);
            # older rows only have the stage chain margin, negative when more than one frame is in flight
            par = throughput == "pipelined" and ((n or 0) > 1 if r.get("sw_margin_basis") else
                                                 r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < 0)
            fps = {"state": "ok", "label": (f"충족 · {n} frame 병렬" if n and n > 1 else "충족 · 병렬 전제") if par else "충족",
                   "cls": "warn" if par else "ok"}
        else:
            val, why = fps_validity(r)
            fps = {"state": "fail", "validity": val, "why": why, "label": "미달" if val == "confirmed" else f"미달 · {VALIDITY_LABEL[val]}",
                   "cls": "fail" if val == "confirmed" else "org"}
        p = (r.get("power") or {}).get("total_mw") if r["spec_ok"] else None
        dist = (r.get("distribution") or {}).get("total_mw") or {}
        o = opts.get((r["scenario_id"], r["variant_id"])) or {}
        best = o.get("best") or {}
        iq = None
        if best:
            st = best.get("review_status") or ("candidate" if best.get("iq_eval") == "required" else "not_required")
            iq = {"saving_mw": best.get("delta_mw"), "status": st, "labels": best.get("labels") or []}
        cls = [fps["cls"]]
        if v is None:
            cls.append("mute")
            if r.get("spec_ok") and not r.get("prediction_id"):
                cls.append("org")  # an unregistered KPI is visible even without a reference
            label = None
        else:
            cls.append({"over": "fail", "conditional": "org", "similar": "warn", "ok": "ok", "na": "mute", "uncovered": "fail"}[v["state"]])
            if v.get("flip"):
                cls.append("fail")
            if not v.get("registered"):
                cls.append("org")
        worst = min(cls, key=lambda x: _RANK[x])
        if v is not None and v.get("flip"):
            label = "불일치 · " + STATE_LABEL[v["state"]]
        elif fps["state"] == "fail":
            label = "fps 미달" if fps["cls"] == "fail" else "검증 필요"
        elif v is None:
            label = ("판정 불가 (기준 없음)" + ("" if r.get("prediction_id") else " · 미등록")) if worst in ("ok", "mute", "warn", "org") else None
        else:
            label = STATE_LABEL[v["state"]] + ("" if v.get("registered") else " · 미등록")
        out.append(k | {
            "covered": True, "scenario_id": r["scenario_id"], "fps": fps, "registered": bool(r.get("prediction_id")),
            "power": {"mw": p, "band": [dist.get("min"), dist.get("max")] if p is not None and dist.get("min") is not None else None},
            "verdict": v, "sw_margin_pct": r.get("sw_margin_pct"), "sw_bottleneck": r.get("sw_bottleneck"), "iq": iq,
            "sw_growth_tolerance": (r.get("sw") or {}).get("growth_tolerance"),
            "sw_growth_tested_max": (r.get("sw") or {}).get("growth_tested_max"),
            "overall": {"cls": worst if worst != "warn" or label else "warn", "label": label or ("주의" if worst == "warn" else "양호")},
        })
    return out


# ------------------------------------------------------------------- lever ladder (actions)
def lever_actions(snap: dict[str, Any], limit_per_tier: int = 3) -> list[dict[str, Any]]:
    """Power-saving actions in the order a project tries them: clock → compression → SW → IQ-degrading options."""
    acts: list[dict[str, Any]] = []
    ok_keys = {(r["scenario_id"], r["variant_id"]) for r in snap.get("scenarios") or [] if r.get("spec_ok")}
    # ① clock: a domain raised above the lowest level that meets the requirement (taken for SW headroom)
    raised: dict[str, dict[str, Any]] = {}
    for d in snap.get("domains") or []:
        if (d["scenario_id"], d["variant_id"]) not in ok_keys or not d.get("raise_mw") or d["raise_mw"] <= 0.5:
            continue
        g = raised.setdefault(d["domain"], {"variants": [], "mw": []})
        g["variants"].append(d["variant_id"])
        g["mw"].append(d["raise_mw"])
    for dom, g in sorted(raised.items(), key=lambda kv: -max(kv[1]["mw"])):
        acts.append({"tier": 1, "action": f"{dom} DVFS를 필요 clock 최소 level로 (+1 level 선택분 회수)", "targets": g["variants"],
                     "delta_mw": -round(max(g["mw"]), 1), "basis": f"SW 여유 확보용 상향 {len(g['variants'])} variant",
                     "check": "SW 여유 · latency 재확인", "iq": False})
    # ② compression: buffers that cut BW but are not selected; lossless first, lossy flagged for an IQ check
    comp = [c for c in snap.get("compression") or [] if c.get("selected", 0) < c.get("variants", 0) and c.get("delta_mw", 0) < -0.5]
    comp.sort(key=lambda c: (bool(c.get("lossy")), c["delta_mw"] / max(1, c["variants"])))
    lossless = [c for c in comp if not c.get("lossy")][:limit_per_tier]
    lossy = [c for c in comp if c.get("lossy")][:limit_per_tier]
    for c in lossless + lossy:
        acts.append({"tier": 2, "action": f"{c['buffer']} compression ({'lossy' if c.get('lossy') else 'lossless'})"
                     + ("" if c.get("support") == "catalog" else " · IP 지원 확인"), "targets": [f"{c['variants']} variant"],
                     "delta_mw": round(c["delta_mw"] / max(1, c["variants"]), 1), "basis": "BW 절감 (variant 평균)",
                     "check": "화질 확인 (lossy)" if c.get("lossy") else "IP 지원 · LLC 할당", "iq": bool(c.get("lossy"))})
    # ③ SW: the common SW bottleneck of low-margin scenarios + recorded CPU placement gains
    low = [{"variant_id": r["variant_id"], "bottleneck": r.get("sw_bottleneck")} for r in snap.get("scenarios") or []
           if r.get("spec_ok") and r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < LOW_MARGIN_PCT] \
        or [m for m in snap.get("sw_margin_top5") or [] if m.get("margin_pct") is not None and m["margin_pct"] < LOW_MARGIN_PCT]
    tasks: dict[str, list[str]] = {}
    for r in low:
        tasks.setdefault(str(r.get("bottleneck") or "—"), []).append(r["variant_id"])
    for task, vids in sorted(tasks.items(), key=lambda kv: -len(kv[1]))[:limit_per_tier]:
        acts.append({"tier": 3, "action": f"{task} 최적화 · HW offload · MID cluster 분산 배치", "targets": vids, "delta_mw": None,
                     "basis": f"SW 여유 < {LOW_MARGIN_PCT:.0f}% {len(vids)} variant", "check": "Perfetto runtime · CPU what-if", "iq": False})
    for c in sorted((c for c in snap.get("cpu") or [] if ((c.get("summary") or {}).get("best_at_start") or {}).get("delta_mw")),
                    key=lambda c: c["summary"]["best_at_start"]["delta_mw"])[:limit_per_tier]:
        b = c["summary"]["best_at_start"]
        if b["delta_mw"] < -0.5:
            acts.append({"tier": 3, "action": f"CPU task 재배치 ({len(b.get('moved') or [])} task)", "targets": [c["variant_id"]],
                         "delta_mw": round(b["delta_mw"], 1), "basis": "CPU what-if 최적 배치", "check": "affinity · EAS 확인", "iq": False})
    # ④ IQ-degrading options: last resort, grouped by the same combination
    groups: dict[str, dict[str, Any]] = {}
    for o in snap.get("power_options") or []:
        b = o.get("best") or {}
        if not b or b.get("delta_mw") is None:
            continue
        g = groups.setdefault(" + ".join(b.get("labels") or []), {"targets": [], "mw": []})
        g["targets"].append(o["variant_id"])
        g["mw"].append(b["delta_mw"])
    for label, g in sorted(groups.items(), key=lambda kv: min(kv[1]["mw"]))[:limit_per_tier]:
        acts.append({"tier": 4, "action": label, "targets": g["targets"], "delta_mw": round(min(g["mw"]), 1),
                     "basis": f"조합 탐색 · {len(g['targets'])} variant (최대 절감)", "check": "IQ 평가 후에만 적용", "iq": True})
    return acts


# ------------------------------------------------------------------- RISK-04 drivers
def drivers(snap: dict[str, Any]) -> list[dict[str, Any]]:
    rows = snap.get("scenarios") or []
    n = len(rows)
    out: list[dict[str, Any]] = []
    low = [r for r in rows if r.get("spec_ok") and r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < LOW_MARGIN_PCT]
    if low:
        tasks: dict[str, int] = {}
        for r in low:
            tasks[str(r.get("sw_bottleneck"))] = tasks.get(str(r.get("sw_bottleneck")), 0) + 1
        top = max(tasks.items(), key=lambda kv: kv[1])
        out.append({"key": "sw_task", "label": f"SW task {top[0]}", "count": top[1], "total": n,
                    "note": f"SW 여유 < {LOW_MARGIN_PCT:.0f}% {len(low)}건 중 {top[1]}건 (음수 {sum(1 for r in low if r['sw_margin_pct'] < 0)})",
                    "check": "전과제 Perfetto runtime · latency 분포, 병렬 instance 수, SW 증가 시 CPU OPP"})
    assumed = sum(1 for r in rows if (r.get("inputs") or {}).get("sw_timing_source") == "assumed")
    if assumed:
        out.append({"key": "sw_assumed", "label": "SW timing 가정값", "count": assumed, "total": n,
                    "note": "측정 기반이 아닌 SW timing", "check": "semantic Perfetto 기반 timing으로 교체"})
    opts = snap.get("power_options") or []
    gated = [o for o in opts if (o.get("best") or {}).get("iq_eval") == "required"]
    if gated:
        out.append({"key": "iq_gated", "label": "추가 절감이 화질 열화 option에 의존", "count": len(gated), "total": n,
                    "note": f"power option 최선 조합 {len(gated)}/{len(opts)} IQ 평가 필요",
                    "check": "clock · compression · SW 여지 먼저 소진, 남는 부족분만 IQ 평가"})
    bias = ((snap.get("model") or {}).get("bias") or {})
    common = [f"{c.upper()} {b['median']:+.0f}%" for c, b in bias.items() if c != "total" and b.get("verdict") == "model_common"]
    if common:
        nb = max((b.get("n") or 0) for b in bias.values())
        out.append({"key": "model_bias", "label": "예측 모델 체계 오차", "count": nb, "total": n, "note": " · ".join(common),
                    "check": "Power fit 보정 · rail별 오차 확인 후 전과제 판정"})
    hi = [r for r in rows if float(r.get("fps") or 0) >= HIGH_FPS]
    if hi:
        out.append({"key": "high_fps", "label": "120 fps 이상 batch 미모델", "count": len(hi), "total": n,
                    "note": f"미달 {sum(1 for r in hi if not r.get('spec_ok'))} · 미등록 {sum(1 for r in hi if not r.get('prediction_id'))}",
                    "check": "HFR batch 크기 · SSM sensor 내부 buffer 반영"})
    if (snap.get("overview") or {}).get("sample_dvfs"):
        out.append({"key": "sample_dvfs", "label": "DVFS table SAMPLE", "count": n, "total": n,
                    "note": "전압 · level 사내 값 아님", "check": "사내 DVFS table 교체"})
    out.sort(key=lambda d: -d["count"])
    return out


# ------------------------------------------------------------------- UX-01 messages and decisions
def messages(snap: dict[str, Any], board: list[dict[str, Any]], verdicts: list[dict[str, Any]]) -> list[str]:
    s = snap.get("spec_summary") or {}
    out = []
    fails = [r for r in snap.get("scenarios") or [] if not r.get("spec_ok")]
    if fails:
        unv = [r for r in fails if fps_validity(r)[0] != "confirmed"]
        t = f"{s.get('explored', 0)}개 중 {s.get('spec_ok', 0)}개 fps 충족. 미달 {len(fails)}개({', '.join(short(r['variant_id']) for r in fails[:3])})"
        t += (" 모두 모델 한계 · 입력 미확정 — 판정 보류, 모델 · 입력 확인 후 재판정." if len(unv) == len(fails)
              else f" 중 확정 {len(fails) - len(unv)}개는 조치 필요.")
        out.append(t)
    else:
        n = s.get('explored', 0)
        out.append(f"평가 완료 {n}개 fps 충족." if n else "fps 평가 완료 결과 없음.")
    if s.get("errors"):
        out[0] = f"[부분 평가] 계산 실패 {len(s['errors'])}개. " + out[0]
    judged = [v for v in verdicts if v["state"] not in ("na", "uncovered")]
    if verdicts:
        flips = [v for v in judged if v.get("flip")]
        over = [v for v in judged if v["state"] == "over"]
        cond = [v for v in judged if v["state"] == "conditional"]
        t = f"전과제 기준 {len(verdicts)}개 중 판정 {len(judged)}개: 이하 {sum(v['state'] in ('ok', 'similar') for v in judged)} · 조건부 {len(cond)} · 초과 {len(over)}"
        if flips:
            t += f". {', '.join(short(v['variant_id']) for v in flips[:2])}는 예측과 실측이 반대 — 전류 목표 달성 미확정"
        elif over or cond:
            t += ". 전류 목표는 " + LADDER_TEXT.split(" → ④")[0] + " 순으로 확보"
        out.append(t + ".")
    else:
        out.append("전과제 비교 기준 없음 — review_policy.power_reference 설정 필요.")
    acts = lever_actions(snap)
    non_iq = [a for a in acts if a["tier"] < 4 and not a["iq"]]
    iq = [a for a in acts if a["tier"] == 4 or a["iq"]]
    if iq and not any(a["delta_mw"] for a in non_iq):
        out.append("추가 절감이 화질 열화 option에만 남아 있음 — clock · compression · SW 여지를 먼저 확인하고, 남는 부족분만 IQ 평가.")
    elif non_iq:
        out.append(f"화질 영향 없는 조치 후보 {len(non_iq)}건(clock · compression · SW)을 먼저 확인, 화질 영향 항목 {len(iq)}건"
                   "(lossy 압축 · 화질 열화 option)은 IQ 평가를 거쳐 마지막에.")
    return out[:3]


_DECISION = {
    "verdict_flip": "전과제 대비 판정 기준을 silicon 실측 우선으로 확정",
    "power_over_reference": "전류 초과 scenario의 절감 계획 승인 (clock → compression → SW 순)",
    "kpi_uncovered": "미커버 KPI scenario 탐색 · 등록 일정",
    "sw_margin_low": "차기 SW 증가 예산 합의 (SW 여유 부족 scenario 기준)",
    "iq_gated_saving": "화질 열화 option IQ 평가 착수 여부 (clock · compression · SW 소진 후)",
    "fps_drop": "fps 미달 scenario의 spec 조정 또는 HW 예산 재배분",
    "spec_up_no_headroom": "spec 상향 scenario의 전력 예산 재합의",
    "sw_growth_budget": "SW 증가 예산 초과 scenario의 clock 상향 비용 수용 또는 SW 최적화 목표 설정",
}


def decisions(risks: list[dict[str, Any]]) -> list[str]:
    out = []
    for r in risks:
        if r.get("status") in ("closed", "accepted") or "resolve_candidate" in (r.get("trend"), r.get("auto_state")):
            continue
        d = _DECISION.get(str(r.get("key")))
        if d and d not in out:
            out.append(d)
    return out[:4]


# ------------------------------------------------------------------- DATA-02 sanity
_RES_KEYS = ("resolution", "fps")


def data_quality(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Input problems that would leak into verdicts: identical results for different specs, missing key conditions,
    fps misses without power, measurements of unknown origin. level: block (publish needs an acknowledgement) · warn · info."""
    rows = snap.get("scenarios") or []
    out: list[dict[str, Any]] = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for r in rows:
        p = r.get("power") or {}
        if r.get("spec_ok") and p.get("total_mw") is not None:
            groups.setdefault((r["scenario_id"], round(float(p["total_mw"]), 1), round(float(r.get("bw_mbs") or 0), 0)), []).append(r)
    for (_, mw, _), g in groups.items():
        # only rows whose resolution and fps are both recorded: a missing condition is reported separately
        full = [r for r in g if all((r.get("conditions") or {}).get(k) is not None for k in _RES_KEYS)]
        conds = {tuple((r.get("conditions") or {}).get(k) for k in _RES_KEYS) for r in full}
        if len(full) > 1 and len(conds) > 1:
            g = full
            out.append({"key": "identical_result", "level": "warn", "variants": [r["variant_id"] for r in g],
                        "text": f"조건이 다른 variant의 예측이 같음 ({mw:,.1f} mW): {', '.join(short(r['variant_id']) for r in g[:4])}",
                        "check": "design_conditions(resolution · fps · sensor mode) 누락 · 기본값 적용 여부"})
    miss = [r for r in rows if r.get("conditions") is not None and any(k not in (r.get("conditions") or {}) for k in _RES_KEYS)]
    if miss:
        out.append({"key": "missing_condition", "level": "warn", "variants": [r["variant_id"] for r in miss],
                    "text": f"resolution · fps 미기재 {len(miss)}건: {', '.join(short(r['variant_id']) for r in miss[:5])}",
                    "check": "variant design_conditions에 resolution · fps 기입"})
    nopw = [r for r in rows if not r.get("spec_ok")]
    if nopw:
        out.append({"key": "fail_without_power", "level": "info", "variants": [r["variant_id"] for r in nopw],
                    "text": f"fps 미달 {len(nopw)}건은 power 미산출 — 전력 · 발열 판정 대상에서 빠짐",
                    "check": "미달 원인 해소 후 재탐색"})
    unknown = [c for c in snap.get("calibration") or [] if not c.get("origin") or c.get("origin") == "unknown"]
    if unknown:
        out.append({"key": "unknown_provenance", "level": "warn", "variants": [c["variant_id"] for c in unknown],
                    "text": f"출처 미기록 실측 {len(unknown)}건 — 판정 근거로 쓰지 않음", "check": "measurement provenance 기록"})
    out += _computation_quality(snap)
    gap = sorted(k["variant_ref"] for k in scoreboard(snap) if not k["covered"]) \
        if ((snap.get("review_context") or {}).get("policy") or {}).get("kpi") else []
    if gap:
        out.append({"key": "kpi_uncovered", "level": "block", "variants": gap,
                    "text": f"KPI scenario 미탐색 {len(gap)}건: {', '.join(short(v) for v in gap)}",
                    "check": "조합 탐색 · 등록 후 재생성, 또는 미포함 사유를 게시 기록에 남김"})
    return out


def _computation_quality(snap: dict[str, Any]) -> list[dict[str, Any]]:
    """Whether the rows were computed alike and with today's code: engine revision, model lineage, power params,
    and CPU what-if snapshots of an older sweep calculation. Only snapshots that record these (engine ≥ 15) are judged."""
    from scenario_db.sim.model_lineage import lineage_key, lineage_label

    rows = snap.get("scenarios") or []
    ov = snap.get("overview") or {}
    out: list[dict[str, Any]] = []
    current = ov.get("engine_current")
    if current:
        old = [r for r in rows if r.get("engine_rev") and r["engine_rev"] != current]
        if old:
            revs = sorted({str(r["engine_rev"]) for r in old})
            out.append({"key": "stale_engine", "level": "block", "variants": [r["variant_id"] for r in old],
                        "text": f"이전 engine으로 계산된 행 {len(old)}/{len(rows)}건 ({', '.join(revs)} → {current}) — 현재 계산 방식과 다름",
                        "check": "현재 engine으로 조합 탐색 · 재등록 후 보고서 재생성 (예측 현황의 '재계산 필요' 확인)"})
    # model lineage: only registered rows count (a fps miss has no registered power)
    lin_rows = [r for r in rows if "model_lineage" in r and r.get("prediction_id")]
    if lin_rows:
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for r in lin_rows:
            groups.setdefault(lineage_key(r.get("model_lineage")), []).append(r)
        if len(groups) > 1:
            ranked = sorted(groups.values(), key=len, reverse=True)
            minority = [r for g in ranked[1:] for r in g]
            out.append({"key": "mixed_lineage", "level": "block", "variants": [r["variant_id"] for r in minority],
                        "text": f"계산 모델이 다른 예측 혼재 — 다수 {len(ranked[0])}건 {lineage_label(ranked[0][0].get('model_lineage'))}, "
                                f"다른 모델 {len(minority)}건 ({', '.join(short(r['variant_id']) for r in minority[:4])}"
                                f"{' 외' if len(minority) > 4 else ''}: {lineage_label(minority[0].get('model_lineage'))})",
                        "check": "같은 config profile(power model · params · BW model)로 재탐색 · 재등록 — variant 간 비교가 모델 차이를 포함함"})
        default = [r for r in lin_rows if not (r.get("model_lineage") or {}).get("power_params_ref")
                   and not (r.get("model_lineage") or {}).get("power_params_hash")]
        if default:
            out.append({"key": "default_params", "level": "warn", "variants": [r["variant_id"] for r in default],
                        "text": f"power params 미지정(코드 기본 계수) 예측 {len(default)}건 — 과제 계수 아님",
                        "check": "과제 config profile(power_params_ref 지정)로 탐색했는지 확인"})
    old_cpu = [c for c in snap.get("cpu") or [] if c.get("calc_current") is False]
    if old_cpu:
        out.append({"key": "cpu_snapshot_stale", "level": "warn", "variants": [c["variant_id"] for c in old_cpu],
                    "text": f"이전 계산 방식의 CPU what-if 결과 {len(old_cpu)}건 (RT chain timing · OPP 계단 기준 변경 전)",
                    "check": "CPU what-if에서 같은 조건으로 계산 후 '갱신'"})
    return out


# ------------------------------------------------------------------- RISK-02 priority
_CAT_W = {"성능": 5, "전력": 4, "발열": 4, "coverage": 4, "화질": 3, "SW": 3, "CPU": 3, "모델": 2, "데이터": 1}
_TIER_W = {"thermal": 2.0, "heavy": 2.0, "base": 1.5}
_SENS = {"verdict_flip": 1.0, "power_over_reference": 0.9, "power_conditional": 0.8, "spec_up_no_headroom": 0.9,
         "kpi_uncovered": 0.9, "sw_growth_budget": 0.7}


def risk_priority(risk: dict[str, Any], snap: dict[str, Any]) -> int:
    """Check order within a severity: customer criterion × KPI weight × how likely the verdict flips (0..100)."""
    tiers = {k["variant_ref"]: k.get("tier") or "base" for k in kpi_list(snap)}
    aff = risk.get("affected") or []
    kpi_w = max((_TIER_W.get(tiers[v], 1.0) for v in aff if v in tiers), default=1.0)
    sens = _SENS.get(str(risk.get("key")), 0.6 if risk.get("validity") not in (None, "confirmed") else 0.5)
    return int(round(_CAT_W.get(str(risk.get("category")), 2) * kpi_w * sens * 10))
