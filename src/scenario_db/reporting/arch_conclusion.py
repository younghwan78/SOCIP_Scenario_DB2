"""Decision layer of the architecture review report (R1 conclusion, R2 model limits, R4 calibration).

Everything is derived from the frozen snapshot, so a regenerated report states the same
conclusion for the same numbers. Nothing here is a measurement unless a calibration row
says so; the confidence grade tells the reader how far to trust the predictions.
"""

from __future__ import annotations

from typing import Any

# Limits that hold for every engine revision so far (kept until the in-house model removes them).
STANDING_LIMITS = (
    "Compression은 BW만 감소 (encoder/decoder 전력 · 화질 영향 미반영). catalog에 없는 ratio는 assumed.",
    "DVFS headroom은 domain 단위 level 상향 (V² scaling), 필요 clock보다 빠른 level만 탐색.",
    "120 fps 이상 NRT batch 처리 미모델 — 고속 recording은 1 frame = 1 period 가정의 보수적 추정.",
)

LOW_MARGIN_PCT = 10.0
FIT_OK_PCT = 10.0
FIT_WARN_PCT = 25.0


def run_lineage(run: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """Model lineage recorded per explored variant (first one) and whether variants disagree."""
    records = [v.get("model_lineage") for v in run.get("variants") or []]
    seen = [x for x in records if x]
    if not seen:
        return (run.get("summary") or {}).get("model_lineage"), False
    first = seen[0]
    return first, any(x != first for x in records)


_PM_TEXT = {
    "1.1": "clock gating · leakage 반영, clock 항 기준 = DVFS 설정 clock",
    "1.2": "clock gating · leakage 반영, clock 항 기준 = margin 없는 work clock (SW margin과 무관)",
}


def model_limits(lineage: dict[str, Any] | None, mixed: bool = False, *, cpu: dict[str, int] | None = None) -> list[str]:
    """Model limits stated from the lineage the run actually used (not a hard-coded list).

    ``cpu``: count of variants per CPU power basis of the objective slice (``flat`` = fps-scaled flat term,
    ``profile`` = measured per-task profile)."""
    lin = lineage or {}
    out: list[str] = []
    if not lineage:
        out.append("이 run에는 model lineage 기록이 없음 (이전 engine) — 아래 한계는 기본 모델 기준.")
    bw = lin.get("bw_power_model") or "builtin"
    if bw == "builtin":
        out.append(f"BW 전력 = MB/s ÷ 1000 × 계수 {lin.get('bw_coefficient', 80)} × LLC weight — MIF DVFS level 미반영.")
    elif bw == "mif-linear":
        out.append(f"BW 전력 = {bw} 모델 (MIF level · read/write 분리 반영).")
    else:
        out.append(f"BW 전력 = {bw} 모델 — MIF DVFS level 미반영.")
    pm = str(lin.get("power_model") or "v1-vfps")
    if pm.startswith("v1"):
        out.append("IP 전력 = 사용률 × 단위전력 × (V/Vref)² × fps 비 — 설정 clock(f_set) · leakage 미반영.")
    elif pm == "v2-vf":
        ver = str(lin.get("power_model_version") or "1.1")   # unrecorded: the formula before versions were recorded
        out.append(f"IP 전력 = {pm} {ver} ({_PM_TEXT.get(ver, 'clock gating · leakage 반영')}).")
    else:
        out.append(f"IP 전력 = {pm} — 해당 모델의 clock · leakage 처리 확인 필요.")
    ref = lin.get("power_params_ref")
    out.append(f"power params = {ref}." if ref else "power params 미지정 — 코드 기본 계수 사용.")
    if str(lin.get("clock_basis") or "calculated") == "calculated":
        out.append("IP clock = 계산값 (실측 clock 미반영).")
    cpu = cpu or {}
    flat, prof = cpu.get("flat", 0), sum(n for k, n in cpu.items() if k != "flat")
    if prof and not flat:
        out.append("CPU 전력 = 실측 CPU profile 기반 (task별 cycle · cluster) — profile 출처(silicon / 합성)와 SW baseline 확인.")
    elif flat:
        out.append(f"CPU 전력 = flat 항 (fps 비례 추정, task 배치 · cluster OPP 미반영) {flat}/{flat + prof}건"
                   + (f", 실측 profile {prof}건" if prof else "")
                   + " — CPU what-if(profile) 결과는 별도 절, 탐색 예측에는 미반영.")
    else:
        out.append("CPU 전력은 cluster · 주파수 · 전압과 계수 기반 추정 — 실측 profile 사용 여부와 계수 검증 필요.")
    if mixed:
        out.append("variant별 model lineage가 서로 다름 — 위 내용은 첫 variant 기준.")
    out.extend(STANDING_LIMITS)
    return out


def calibration_row(variant_id: str, scenario_id: str, detail: dict[str, Any], prediction_id: str | None) -> dict[str, Any] | None:
    """One report row from ``calibration.measurement_detail``: the prediction registered from this run vs the measurement."""
    from scenario_db.comparison.calibration import category_fit

    pred = next((p for p in detail.get("predictions") or [] if p.get("kind") == "current"
                 and (prediction_id is None or p.get("id") == prediction_id)), None)
    if pred is None:
        return None
    rows = pred.get("rows") or []
    return {
        "scenario_id": scenario_id, "variant_id": variant_id, "measurement_id": detail.get("id"),
        "measured_at": detail.get("measured_at"), "synthetic": bool(detail.get("synthetic")),
        "origin": detail.get("origin") or ("synthetic" if detail.get("synthetic") else "physical_capture"),
        "measured_mw": (detail.get("total") or {}).get("mean"), "predicted_mw": pred.get("total_mw"),
        "delta_pct": pred.get("delta_pct"),
        "rows": [{k: r.get(k) for k in ("category", "prediction_mw", "measurement_mw", "delta_pct")} for r in rows],
        "unmodeled_mw": next((r.get("measurement_mw") for r in rows if r.get("category") == "other"), None),
        "fit": category_fit(rows, pred.get("delta_pct")),
    }


def _is_real(c: dict[str, Any]) -> bool:
    """Silicon capture only; unknown origin is not accuracy evidence (pre-origin snapshots: not synthetic)."""
    origin = c.get("origin")
    return origin == "physical_capture" if origin else not c["synthetic"]


def _confidence(snap: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    weak_input = bool(snap["overview"].get("sample_dvfs")) or not snap["overview"].get("dvfs_table_ref")
    if snap["overview"].get("sample_dvfs"):
        reasons.append("DVFS table이 SAMPLE — 전압 · level이 사내 값이 아님")
    elif not snap["overview"].get("dvfs_table_ref"):
        reasons.append("run에 DVFS table 기록 없음 (이전 engine) — 어떤 전압 · level 기준인지 확인 불가")
    return calibration_confidence(snap.get("calibration") or [], input_reasons=reasons, weak_input=weak_input)


GRADE_MEANING = {"A": "실측 대조 구성 오차 ≤10% — 대조 범위 내 검토 가능",
                 "B": "실측 대조 있음 — 구성 오차 · 상쇄를 확인하며 경향 비교",
                 "C": "실측 근거 부족 또는 SAMPLE 입력 — 상대 비교 · 후보 선정 용도"}


def calibration_confidence(cal: list[dict[str, Any]], *, input_reasons: list[str] | None = None,
                           weak_input: bool = False) -> dict[str, Any]:
    """Model confidence grade shared by the report conclusion and the calibration summary (CAL-06).

    ``cal`` rows carry ``origin`` / ``synthetic`` and ``fit`` (``category_fit``); a real capture
    only counts when it can be compared category by category.
    """
    reasons = list(input_reasons or [])
    real = [c for c in cal if _is_real(c) and c["fit"]["worst_delta_pct"] is not None]
    worst = max((abs(c["fit"]["worst_delta_pct"]) for c in real), default=None)
    if not real:
        reasons.append("실제 silicon 측정과 대조한 variant 없음" + (f" (합성 fixture {len(cal)}건은 근거 아님)" if cal else ""))
    elif worst is not None and worst > FIT_WARN_PCT:
        reasons.append(f"실측 대조 CPU · IP · BW 중 최대 |Δ| {worst:.0f}% (> {FIT_WARN_PCT:.0f}%)")
    if any(c["fit"]["offsetting"] for c in real):
        reasons.append("total은 실측과 맞지만 구성 오차가 상쇄된 variant 있음 — what-if 절감량 신뢰 낮음")
    if reasons:
        grade = "C" if (weak_input or not real) else "B"
    elif worst is not None and worst <= FIT_OK_PCT:
        grade = "A"
    else:
        grade = "B"
        reasons.append(f"실측 대조 최대 |Δ| {worst:.0f}% (≤ {FIT_WARN_PCT:.0f}%)" if worst is not None else "실측 대조 구성 비교 불가")
    return {"grade": grade, "reasons": reasons, "meaning": GRADE_MEANING[grade], "real": len(real), "compared": len(cal)}


def build_conclusion(snap: dict[str, Any]) -> dict[str, Any]:
    s = snap["spec_summary"]
    risks: list[dict[str, str]] = []
    errors = s.get("errors") or []
    if errors:
        cats = sorted({f"{e.get('stage')}/{e.get('category')}" for e in errors})
        risks.append({"title": f"계산 실패 {len(errors)}/{s.get('requested', s['explored'] + len(errors))} — 부분 평가",
                      "detail": f"{', '.join(str(e.get('variant_id')) for e in errors[:5])}{' …' if len(errors) > 5 else ''} "
                                f"({', '.join(cats)}) — 결론은 평가 완료 scenario만 대상"})
    if s["spec_fail"]:
        names = [f["variant_id"] for f in s["failed"]]
        first = next(((f.get("explained") or [{"text": r} for r in f["reasons"]])[0]["text"]
                      for f in s["failed"] if f.get("explained") or f["reasons"]), "")
        risks.append({"title": f"spec 미달 {s['spec_fail']}/{s['explored']}",
                      "detail": f"{', '.join(names[:5])}{' …' if len(names) > 5 else ''} — {first}"})
    # SW-01: every spec-ok scenario, not only the Top-5 table
    low = ([{"variant_id": r["variant_id"], "margin_pct": r["sw_margin_pct"], "stage": r.get("sw_stage"), "bottleneck": r.get("sw_bottleneck"),
             "tolerance": (r.get("sw") or {}).get("growth_tolerance"), "tested": (r.get("sw") or {}).get("growth_tested_max")}
            for r in sorted((r for r in snap.get("scenarios") or [] if r.get("spec_ok") and r.get("sw_margin_pct") is not None
                             and r["sw_margin_pct"] < LOW_MARGIN_PCT), key=lambda r: r["sw_margin_pct"])]
           or [m | {"tolerance": m.get("growth_tolerance")} for m in snap.get("sw_margin_top5") or []
               if m.get("margin_pct") is not None and m["margin_pct"] < LOW_MARGIN_PCT])
    if low:
        m0 = low[0]
        risks.append({"title": f"SW timing margin < {LOW_MARGIN_PCT:.0f}% · {len(low)}건",
                      "detail": f"최소 {m0['margin_pct']:.1f}% ({m0['variant_id']}, {str(m0.get('stage', '')).upper()}, "
                                f"병목 {m0.get('bottleneck')}) — " + _growth_outlook(low, snap)})
    off = [c for c in snap.get("calibration") or [] if c["fit"]["offsetting"] and _is_real(c)]
    if off:
        risks.append({"title": f"예측 구성 오차 상쇄 {len(off)}건",
                      "detail": ", ".join(f"{c['variant_id']} {c['fit']['worst_category']} {c['fit']['worst_delta_pct']:+.0f}%" for c in off[:3])})
    if snap["overview"].get("sample_dvfs"):
        risks.append({"title": "DVFS table SAMPLE", "detail": f"{snap['overview'].get('dvfs_table_ref')} — 사내 table 교체 전 전압 · level 비교는 참고용"})
    elif not snap["overview"].get("dvfs_table_ref"):
        risks.append({"title": "DVFS table 미기록", "detail": "이전 engine run이라 사용한 DVFS table이 기록되지 않음 — 현재 engine으로 재탐색 권장"})

    # lever ladder: ① clock → ② compression → ③ SW → ④ IQ-degrading options (last resort), grouped across variants
    from scenario_db.reporting.review_verdict import LADDER, lever_actions

    actions: list[dict[str, Any]] = []
    for a in lever_actions(snap, limit_per_tier=2):
        t = a["targets"]
        actions.append({"tier": a["tier"], "tier_label": LADDER[a["tier"]][1], "action": a["action"],
                        "target": f"{_s(t[0])}{f' 외 {len(t) - 1}' if len(t) > 1 else ''}" if t else "—", "targets": t,
                        "delta_mw": a["delta_mw"], "delta_pct": None, "basis": a["basis"], "check": a["check"], "iq": a["iq"]})
    by_code: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for f in s["failed"]:
        for e in f.get("explained") or []:
            if e["code"] != "interval":  # intervals follow from the stage overrun
                by_code.setdefault(e["code"], []).append((f["variant_id"], e))
    for code, items in sorted(by_code.items(), key=lambda kv: -len(kv[1]))[:2]:
        names = sorted({v for v, _ in items})
        act = items[0][1].get("action")
        actions.append({"tier": 0, "tier_label": "fps 미달",
                        "action": act if act not in (None, "", "—") else "batch · 병렬 처리 반영 후 재판정 (모델 · 입력 확인)",
                        "target": f"{_s(names[0])}{f' 외 {len(names) - 1}' if len(names) > 1 else ''}", "targets": names,
                        "delta_mw": None, "delta_pct": None, "basis": f"spec 미달 · {items[0][1]['text']}",
                        "check": "batch 모델 + 실측" if code == "sw_budget" else "IP 처리량 · DVFS table 확인", "iq": False})
    if s["spec_fail"] and not by_code:
        actions.append({"tier": 0, "tier_label": "fps 미달", "action": "NRT batch · SW 병렬화 또는 HW 예산 재배분",
                        "target": f"spec 미달 {s['spec_fail']}건", "targets": [], "delta_mw": None,
                        "delta_pct": None, "basis": "timing budget", "check": "batch 모델 + 실측", "iq": False})
    actions.sort(key=lambda a: a["tier"])
    ok, n = s["spec_ok"], s["explored"]
    rng = s.get("power_range_mw")
    sources = s.get("power_sources") or {}
    source = ("등록 예측 · 탐색 추천" if sources.get("registered") and sources.get("recommended") else
              "등록 예측" if sources.get("registered") else "탐색 추천" if sources.get("recommended") else "예측")
    prefix = (f"[부분 평가] 요청 {s.get('requested', n + len(errors))}개 중 계산 실패 {len(errors)}개 · " if errors else "")
    headline = (prefix + f"탐색 {n}개 중 {ok}개 spec 만족" + (f", {source} {rng[0]:,.0f}–{rng[1]:,.0f} mW" if rng else "")
                + (f". 미달 {n - ok}개는 조치 필요" if n - ok else (". 평가 완료분 미달 없음" if errors else ". 미달 없음")))
    return {"headline": headline, "risks": risks[:3], "actions": actions[:10], "confidence": _confidence(snap)}


def _growth_outlook(low: list[dict[str, Any]], snap: dict[str, Any]) -> str:
    """What a low margin means for the next SW: judged by the SW growth the timing absorbs (DVFS re-selected),
    against the project's SW growth budget — not by the margin sign alone."""
    budget = (((snap.get("review_context") or {}).get("policy") or {}).get("sw_growth_budget"))
    tols = [m for m in low if m.get("tolerance") is not None]
    if not tols:
        return "SW 증가 허용 미산출 — SW 증가 slice로 확인 필요"
    t0 = min(tols, key=lambda m: float(m["tolerance"]))
    tol = float(t0["tolerance"])
    capped = t0.get("tested") is not None and tol >= float(t0["tested"]) - 1e-6
    txt = f"증가 허용 최소 {'≥' if capped else ''}×{tol:.2f} ({t0['variant_id']})"
    if budget is None:
        return txt + " — SW 증가 예산(review_policy.sw_growth_budget) 미지정"
    if tol >= float(budget) - 1e-6:
        return txt + f" ≥ 예산 ×{float(budget):.2f} — 예산 안의 SW 증가는 흡수 (DVFS 재선택 포함)"
    if capped:
        return txt + f" — 예산 ×{float(budget):.2f}까지 미검증"
    return txt + f" < 예산 ×{float(budget):.2f} — 차기 SW 증가 시 clock 상향 또는 SW 최적화 필요"


def _s(v: str) -> str:
    return str(v).replace("cam-rec-", "")
