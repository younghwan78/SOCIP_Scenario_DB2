"""Automatic review risks of a project report (RPT-04).

Every rule reads the frozen snapshot only, so the same snapshot yields the same risks. A rule
returns at most one risk with a stable ``key``; the register (``review_risks``) keeps the rows
across reports and people own owner / status / note.

Severity follows the customer review rules (review_policy):
  critical  fps drop (spec miss under the current throughput model)
  high      power above the previous project · comparison variant without prediction ·
            thermal 10 % ask unreachable with IQ-keeping levers · calculation failures
  medium    thermal 20 % ask unreachable · SW margin < 10 % · model-wide prediction error
  info      SAMPLE inputs / no silicon measurement
"""

from __future__ import annotations

from typing import Any

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}
SEVERITY_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "info": "Info"}
LOW_MARGIN_PCT = 10.0


def _short(v: str) -> str:
    return str(v).replace("cam-rec-", "")


def _names(vs: list[str], n: int = 4) -> str:
    vs = [_short(v) for v in vs]
    return ", ".join(vs[:n]) + (f" 외 {len(vs) - n}" if len(vs) > n else "")


def build_risks(snap: dict[str, Any]) -> list[dict[str, Any]]:
    s = snap.get("spec_summary") or {}
    ov = snap.get("overview") or {}
    ctx = snap.get("review_context") or {}
    throughput = ((ctx.get("policy") or {}).get("throughput_model")) or "stage"
    risks: list[dict[str, Any]] = []

    errors = s.get("errors") or []
    if errors:
        vids = [str(e.get("variant_id")) for e in errors]
        risks.append({"key": "calc_failed", "rule": "calc_failed", "severity": "high", "category": "데이터",
                      "title": f"계산 실패 {len(errors)}건 — 부분 평가",
                      "detail": f"{_names(vids)}: {str(errors[0].get('error') or '')[:160]}",
                      "affected": vids, "mitigation": "입력(catalog · DVFS · SW timing) 확인 후 재탐색"})

    failed = s.get("failed") or []
    if failed:
        vids = [f["variant_id"] for f in failed]
        first: dict[str, Any] = next(((f.get("explained") or [{}])[0] for f in failed if f.get("explained")), {})
        reason = first.get("text") or next((f["reasons"][0] for f in failed if f.get("reasons")), "")
        risks.append({"key": "fps_drop", "rule": "fps_drop", "severity": "critical", "category": "성능",
                      "title": f"fps 미달 {len(failed)}/{s.get('explored', len(failed))} variant ({throughput} 기준)",
                      "detail": f"{_names(vids)} — {reason}", "affected": vids,
                      "mitigation": (first.get("action") if first.get("action") not in (None, "", "—") else None)
                      or "NRT batch · SW 병렬화 또는 HW 예산 재배분"})

    over = [r for r in ctx.get("rows") or [] if (r.get("reference") or {}).get("status") == "over"]
    if over:
        over.sort(key=lambda r: -(r["reference"].get("delta_pct") or 0))
        risks.append({"key": "power_over_reference", "rule": "power_over_reference", "severity": "high", "category": "전력",
                      "title": f"전과제 대비 전력 초과 {len(over)}건",
                      "detail": ", ".join(f"{_short(r['variant_id'])} {r['total_mw']:.0f} mW ({r['reference']['delta_pct']:+.1f}%)" for r in over[:4]),
                      "affected": [r["variant_id"] for r in over],
                      "mitigation": "lever 분석의 화질 유지 lever 적용 → 부족분은 IQ 평가 대상 lever"})

    ref = snap.get("reference_check") or {}
    missing = ref.get("missing") or []
    if missing:
        risks.append({"key": "reference_missing", "rule": "reference_missing", "severity": "high", "category": "전력",
                      "title": f"전과제 비교 기준 variant 예측 없음 {len(missing)}/{ref.get('total', len(missing))}",
                      "detail": f"{_names(missing)} — 전과제 대비 전류 판정 불가", "affected": missing,
                      "mitigation": "조합 탐색에 포함해 예측 등록 후 보고서 재생성"})

    thermal = snap.get("thermal") or {}
    for pct, sev in ((10, "high"), (20, "medium")):
        # a −20 % miss only adds information when −10 % is reachable (otherwise the −10 % risk already covers it)
        short = [i for i in thermal.get("items") or [] if any(p["ask_pct"] == pct and not p["achieved"] for p in i.get("plans") or [])
                 and (pct == 10 or all(p["achieved"] for p in i.get("plans") or [] if p["ask_pct"] < pct))]
        if short:
            det = "; ".join(f"{_short(i['variant_id'])} 필요 {next(p['need_mw'] for p in i['plans'] if p['ask_pct'] == pct):.0f} mW, "
                            f"IQ 항목 최대 {next(p['saving_mw'] for p in i['plans'] if p['ask_pct'] == pct):.0f} mW" for i in short[:3])
            risks.append({"key": f"thermal_{pct}", "rule": "thermal_unreachable", "severity": sev, "category": "발열",
                          "title": f"발열 대응 −{pct}% 미달 {len(short)}건 (IQ 유지 lever 기준)", "detail": det,
                          "affected": [i["variant_id"] for i in short],
                          "mitigation": "성능 trade 후보(해상도 · fps · EIS)를 IQ 평가에 포함"})
    unassessed = [i["variant_id"] for i in thermal.get("items") or [] if i.get("current_mw") is None]
    if unassessed:
        risks.append({"key": "thermal_unassessed", "rule": "thermal_unassessed", "severity": "medium", "category": "발열",
                      "title": f"발열 감시 variant 미평가 {len(unassessed)}건", "detail": f"{_names(unassessed)} — 조합 탐색 결과 없음",
                      "affected": unassessed, "mitigation": "power option을 켜고 조합 탐색 실행"})

    low = [m for m in snap.get("sw_margin_top5") or [] if m.get("margin_pct") is not None and m["margin_pct"] < LOW_MARGIN_PCT]
    if low:
        m0 = low[0]
        risks.append({"key": "sw_margin_low", "rule": "sw_margin_low", "severity": "medium", "category": "SW",
                      "title": f"SW timing margin < {LOW_MARGIN_PCT:.0f}% · {len(low)}건",
                      "detail": f"최소 {m0['margin_pct']:.1f}% ({_short(m0['variant_id'])}, {str(m0.get('stage', '')).upper()}, 병목 {m0.get('bottleneck')})",
                      "affected": [m["variant_id"] for m in low], "mitigation": f"{m0.get('bottleneck')} 최적화 · HW offload · core 배치 검토"})

    model = snap.get("model") or {}
    common = [(c, b) for c, b in (model.get("bias") or {}).items() if c != "total" and b.get("verdict") == "model_common"]
    if common or model.get("offsetting"):
        parts = [f"{c.upper()} {b['median']:+.0f}%" for c, b in common]
        risks.append({"key": "model_bias", "rule": "model_bias", "severity": "medium", "category": "모델",
                      "title": "예측 모델 공통 오차" + (f": {' · '.join(parts)}" if parts else ""),
                      "detail": (f"구성 median Δ {', '.join(parts)} (같은 방향 ≥ 80%)" if parts else "")
                      + (f"{' · ' if parts else ''}total ±10% 이내 중 상쇄 {model.get('offsetting')}건" if model.get("offsetting") else ""),
                      "affected": [], "mitigation": "Power fit으로 구성 계수 보정 · CPU 모델 profile 전환 검토"})

    sample = []
    if ov.get("sample_dvfs"):
        sample.append(f"DVFS table SAMPLE ({ov.get('dvfs_table_ref')})")
    origin = (model.get("coverage") or {}).get("origin") or {}
    if model and not origin.get("physical_capture"):
        sample.append(f"실측 대조 silicon capture 없음 (합성 {origin.get('synthetic', 0)}건)")
    if sample:
        risks.append({"key": "sample_input", "rule": "sample_input", "severity": "info", "category": "데이터",
                      "title": "SAMPLE 입력 · 실측 근거 부족", "detail": " · ".join(sample), "affected": [],
                      "mitigation": "사내 DVFS table · silicon capture로 교체"})
    risks.sort(key=lambda r: SEVERITY_ORDER[r["severity"]])
    return risks


def risk_counts(register: list[dict[str, Any]]) -> dict[str, int]:
    """Open (not closed / accepted) risks per severity — the Portfolio cell."""
    out = {k: 0 for k in SEVERITY_ORDER}
    for r in register:
        if r.get("status") not in ("closed", "accepted") and r.get("auto_state") != "resolve_candidate":
            out[r["severity"]] = out.get(r["severity"], 0) + 1
    return out
