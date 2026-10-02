"""Decision layer of the architecture review report (R1 conclusion, R2 model limits, R4 calibration).

Everything is derived from the frozen snapshot, so a regenerated report states the same
conclusion for the same numbers. Nothing here is a measurement unless a calibration row
says so; the confidence grade tells the reader how far to trust the predictions.
"""

from __future__ import annotations

from typing import Any

# Limits that hold for every engine revision so far (kept until the in-house model removes them).
STANDING_LIMITS = (
    "CPU 전력은 cluster · 주파수 · 전압 가정 (Linux EM 계수 × busy time) — 실측 residency 미반영.",
    "Compression은 BW만 감소 (encoder/decoder 전력 · 화질 영향 미반영). catalog에 없는 ratio는 assumed.",
    "DVFS headroom은 domain 단위 level 상향 (V² scaling), 필요 clock보다 빠른 level만 탐색.",
    "120 fps 이상 NRT batch 처리 미모델 — 고속 recording은 1 frame = 1 period 가정의 보수적 추정.",
)

LOW_MARGIN_PCT = 10.0
FIT_OK_PCT = 10.0
FIT_WARN_PCT = 25.0


def model_limits(lineage: dict[str, Any] | None) -> list[str]:
    """Model limits stated from the lineage the run actually used (not a hard-coded list)."""
    lin = lineage or {}
    out: list[str] = []
    if not lineage:
        out.append("이 run에는 model lineage 기록이 없음 (이전 engine) — 아래 한계는 기본 모델 기준.")
    bw = lin.get("bw_power_model") or "builtin"
    if bw == "builtin":
        out.append(f"BW 전력 = MB/s × 계수 {lin.get('bw_coefficient', 80)} — MIF DVFS level 미반영.")
    else:
        out.append(f"BW 전력 = {bw} 모델 (MIF level · read/write 분리 반영).")
    pm = str(lin.get("power_model") or "v1-vfps")
    if pm.startswith("v1"):
        out.append("IP 전력 = 사용률 × 단위전력 × (V/Vref)² × fps 비 — 설정 clock(f_set) · leakage 미반영.")
    else:
        out.append(f"IP 전력 = {pm} (clock gating · leakage 반영).")
    ref = lin.get("power_params_ref")
    out.append(f"power params = {ref}." if ref else "power params 미지정 — 코드 기본 계수 사용.")
    if str(lin.get("clock_basis") or "calculated") == "calculated":
        out.append("IP clock = 계산값 (실측 clock 미반영).")
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
        "measured_mw": (detail.get("total") or {}).get("mean"), "predicted_mw": pred.get("total_mw"),
        "delta_pct": pred.get("delta_pct"),
        "rows": [{k: r.get(k) for k in ("category", "prediction_mw", "measurement_mw", "delta_pct")} for r in rows],
        "unmodeled_mw": next((r.get("measurement_mw") for r in rows if r.get("category") == "other"), None),
        "fit": category_fit(rows, pred.get("delta_pct")),
    }


def _confidence(snap: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    cal = snap.get("calibration") or []
    real = [c for c in cal if not c["synthetic"]]
    worst = max((abs(c["fit"]["worst_delta_pct"]) for c in real if c["fit"]["worst_delta_pct"] is not None), default=None)
    if snap["overview"].get("sample_dvfs"):
        reasons.append("DVFS table이 SAMPLE — 전압 · level이 사내 값이 아님")
    if not real:
        reasons.append("실제 silicon 측정과 대조한 variant 없음" + (f" (합성 fixture {len(cal)}건은 근거 아님)" if cal else ""))
    elif worst is not None and worst > FIT_WARN_PCT:
        reasons.append(f"실측 대조 CPU · IP · BW 중 최대 |Δ| {worst:.0f}% (> {FIT_WARN_PCT:.0f}%)")
    if any(c["fit"]["offsetting"] for c in real):
        reasons.append("total은 실측과 맞지만 구성 오차가 상쇄된 variant 있음 — what-if 절감량 신뢰 낮음")
    if reasons:
        grade = "C" if (snap["overview"].get("sample_dvfs") or not real) else "B"
    else:
        grade = "A" if worst is not None and worst <= FIT_OK_PCT else "B"
        if grade == "B":
            reasons.append(f"실측 대조 최대 |Δ| {worst:.0f}% (≤ {FIT_WARN_PCT:.0f}%)")
    return {"grade": grade, "reasons": reasons,
            "meaning": {"A": "실측 대조 구성 오차 ≤10% — 수치 그대로 검토 가능",
                        "B": "실측 대조 있음, 구성 오차 ≤25% — 경향 비교 용도",
                        "C": "실측 근거 부족 또는 SAMPLE 입력 — 상대 비교 · 후보 선정 용도"}[grade]}


def build_conclusion(snap: dict[str, Any]) -> dict[str, Any]:
    s = snap["spec_summary"]
    risks: list[dict[str, str]] = []
    if s["spec_fail"]:
        names = [f["variant_id"] for f in s["failed"]]
        first = next((f["reasons"][0] for f in s["failed"] if f["reasons"]), "")
        risks.append({"title": f"spec 미달 {s['spec_fail']}/{s['explored']}",
                      "detail": f"{', '.join(names[:5])}{' …' if len(names) > 5 else ''} — {first}"})
    low = [m for m in snap.get("sw_margin_top5") or [] if m.get("margin_pct") is not None and m["margin_pct"] < LOW_MARGIN_PCT]
    if low:
        m0 = low[0]
        risks.append({"title": f"SW timing margin < {LOW_MARGIN_PCT:.0f}% · {len(low)}건",
                      "detail": f"최소 {m0['margin_pct']:.1f}% ({m0['variant_id']}, {str(m0.get('stage', '')).upper()}, "
                                f"병목 {m0.get('bottleneck')}) — 차기 SW 증가 시 clock 상향 필요"})
    off = [c for c in snap.get("calibration") or [] if c["fit"]["offsetting"] and not c["synthetic"]]
    if off:
        risks.append({"title": f"예측 구성 오차 상쇄 {len(off)}건",
                      "detail": ", ".join(f"{c['variant_id']} {c['fit']['worst_category']} {c['fit']['worst_delta_pct']:+.0f}%" for c in off[:3])})
    if snap["overview"].get("sample_dvfs"):
        risks.append({"title": "DVFS table SAMPLE", "detail": f"{snap['overview'].get('dvfs_table_ref')} — 사내 table 교체 전 전압 · level 비교는 참고용"})

    actions: list[dict[str, Any]] = []
    for o in sorted((o for o in snap.get("power_options") or [] if o.get("best")), key=lambda o: o["best"]["delta_mw"])[:3]:
        b = o["best"]
        actions.append({"action": " + ".join(b["labels"]), "target": o["variant_id"], "delta_mw": b["delta_mw"],
                        "delta_pct": b["delta_pct"], "basis": "derived (조합 탐색)", "check": "IQ 평가"})
    seen: set[str] = set()
    for m in low:
        task = str(m.get("bottleneck"))
        if task in seen:
            continue
        seen.add(task)
        actions.append({"action": f"{task} 최적화 · HW offload · big core 배치 검토", "target": m["variant_id"], "delta_mw": None,
                        "delta_pct": None, "basis": f"SW margin {m['margin_pct']:.1f}% (SW 가정 기반)", "check": "CPU profile 실측"})
    if s["spec_fail"]:
        actions.append({"action": "NRT batch · SW 병렬화 또는 HW 예산 재배분", "target": f"spec 미달 {s['spec_fail']}건", "delta_mw": None,
                        "delta_pct": None, "basis": "timing budget", "check": "batch 모델 + 실측"})
    ok, n = s["spec_ok"], s["explored"]
    rng = s.get("power_range_mw")
    headline = (f"탐색 {n}개 중 {ok}개 spec 만족" + (f", 등록 예측 {rng[0]:,.0f}–{rng[1]:,.0f} mW" if rng else "")
                + (f". 미달 {n - ok}개는 조치 필요" if n - ok else ". 미달 없음"))
    return {"headline": headline, "risks": risks[:3], "actions": actions[:5], "confidence": _confidence(snap)}
