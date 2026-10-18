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

RISK-01: every risk carries ``validity`` (confirmed · model_limit · input_unverified); Critical is kept only for
confirmed findings. ``checks`` lists what to confirm first. Power mitigations follow the lever ladder
(clock → compression → SW → IQ-degrading options last).
"""

from __future__ import annotations

from typing import Any

from scenario_db.reporting.review_verdict import (
    LADDER_TEXT,
    STATE_LABEL,
    VALIDITY_LABEL,
    data_quality,
    fps_validity,
    power_verdicts,
    risk_priority,
    scoreboard,
)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}
SEVERITY_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "info": "Info"}
LOW_MARGIN_PCT = 10.0
CPU_TOLERANCE_MIN = 1.2   # SW growth the CPU placement must absorb without an OPP step / timing loss


def _short(v: str) -> str:
    return str(v).replace("cam-rec-", "")


def _names(vs: list[str], n: int = 4) -> str:
    vs = [_short(v) for v in vs]
    return ", ".join(vs[:n]) + (f" 외 {len(vs) - n}" if len(vs) > n else "")


def _failure_validity(snap: dict[str, Any], failure: dict[str, Any]) -> tuple[str, str]:
    rows = [r for r in snap.get("scenarios") or [] if not r.get("spec_ok") and r["variant_id"] == failure["variant_id"]
            and (not failure.get("scenario_id") or r.get("scenario_id") == failure["scenario_id"])]
    found = [fps_validity(r) for r in rows]
    if not found or any(v == "confirmed" for v, _ in found):
        return "confirmed", ""
    return min(found, key=lambda v: v[0] != "model_limit")


def _validity_of(snap: dict[str, Any], failures: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """RISK-01: worst-case validity of the affected variants (any confirmed → confirmed)."""
    found = [_failure_validity(snap, f) for f in failures]
    if not found or any(v == "confirmed" for v, _ in found):
        return "confirmed", []
    kinds = sorted({v for v, _ in found}, key=lambda k: k != "model_limit")
    return kinds[0], sorted({w for _, w in found if w})


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
                      "affected": vids, "mitigation": "입력(catalog · DVFS · SW timing) 확인 후 재탐색",
                      "checks": ["계산 오류 메시지 확인", "입력 catalog · DVFS table · SW timing 확인", "재탐색"]})

    failed = s.get("failed") or []
    if failed:
        groups: dict[str, list[dict[str, Any]]] = {}
        for f in failed:
            val = _failure_validity(snap, f)[0]
            groups.setdefault("confirmed" if val == "confirmed" else "unverified", []).append(f)
        for grp, items in groups.items():
            vids = [f["variant_id"] for f in items]
            first: dict[str, Any] = next(((f.get("explained") or [{}])[0] for f in items if f.get("explained")), {})
            reason = first.get("text") or next((f["reasons"][0] for f in items if f.get("reasons")), "")
            act = first.get("action") if first.get("action") not in (None, "", "—") else None
            if grp == "confirmed":
                risks.append({"key": "fps_drop", "rule": "fps_drop", "severity": "critical", "category": "성능",
                              "title": f"fps 미달 {len(items)}/{s.get('explored', len(failed))} variant ({throughput} 기준)",
                              "detail": f"{_names(vids)} — {reason}", "affected": vids, "validity": "confirmed",
                              "mitigation": act or "NRT batch · SW 병렬화 또는 HW 예산 재배분",
                              "checks": ["병목 stage · task 확인 (Timing Budget)", "clock 상향 여지 (DVFS)", "SW 병렬화 · batch"]})
            else:
                validity, why = _validity_of(snap, items)
                risks.append({"key": "fps_drop_unverified", "rule": "fps_drop", "severity": "high", "category": "성능",
                              "title": f"fps 미달 {len(items)}/{s.get('explored', len(failed))} variant — 검증 필요 ({VALIDITY_LABEL[validity]})",
                              "detail": f"{_names(vids)} — {reason}" + (f" · 근거: {'; '.join(why[:2])}" if why else ""),
                              "affected": vids, "validity": validity,
                              "mitigation": "판정 보류 — 모델 한계 · 미확정 입력을 해소한 뒤 재판정"
                              + (f" (조치 후보: {act})" if act else ""),
                              "checks": ["HFR batch 크기 · SSM sensor 내부 buffer 반영 여부", "sensor mode 지원 확인",
                                         "측정 기반 SW timing으로 재평가", "실측 fps (silicon)"]})

    verdicts = power_verdicts(snap)
    policy = (snap.get("review_context") or {}).get("policy") or {}
    board = scoreboard(snap, verdicts) if snap.get("scenarios") is not None and policy else []
    uncovered = [k for k in board if not k.get("covered")] if policy.get("kpi") else []
    kpi_gap = {k["variant_ref"] for k in uncovered}  # one risk per gap: reference / thermal rules skip these
    if verdicts:  # REF-05: verdict over prediction + range + bias-corrected prediction + silicon measurement
        over = sorted([v for v in verdicts if v["state"] == "over"], key=lambda v: -((v["meas_pct"] if v["basis"] == "measurement" else v["pred_pct"]) or 0))
        if over:
            risks.append({"key": "power_over_reference", "rule": "power_over_reference", "severity": "high", "category": "전력",
                          "title": f"전과제 대비 전력 초과 {len(over)}건",
                          "detail": ", ".join(f"{_short(v['variant_id'])} {(v['meas_mw'] if v['basis'] == 'measurement' else v['pred_mw']):.0f} mW "
                                              f"({(v['meas_pct'] if v['basis'] == 'measurement' else v['pred_pct']):+.1f}%, "
                                              f"{'실측' if v['basis'] == 'measurement' else '예측'})" for v in over[:4]),
                          "affected": [v["variant_id"] for v in over], "validity": "confirmed",
                          "mitigation": LADDER_TEXT, "checks": _POWER_CHECKS})
        flips = [v for v in verdicts if v.get("flip")]
        if flips:
            risks.append({"key": "verdict_flip", "rule": "verdict_flip", "severity": "high", "category": "전력",
                          "title": f"전과제 판정 예측 ↔ 실측 반대 {len(flips)}건",
                          "detail": "; ".join(f"{_short(v['variant_id'])} 예측 {v['pred_pct']:+.1f}% · 실측 {v['meas_pct']:+.1f}% "
                                              f"(기준 {v['ref_mw']:.0f} mW)" for v in flips[:3]),
                          "affected": [v["variant_id"] for v in flips], "validity": "confirmed",
                          "mitigation": "실측 기준으로 판정 · rail별 오차(CPU · IP · BW) 보정 후 재예측",
                          "checks": ["실측 capture provenance (silicon / 합성)", "rail별 Δ (예측 ↔ 실측)", "보정 계수 적용 재예측"]})
        cond = [v for v in verdicts if v["state"] == "conditional"]
        if cond:
            risks.append({"key": "power_conditional", "rule": "band_cross", "severity": "medium", "category": "전력",
                          "title": f"전과제 대비 조건부 {len(cond)}건 — 범위 · 보정 시 허용 초과",
                          "detail": "; ".join(f"{_short(v['variant_id'])} ({v['why']})" for v in cond[:3]),
                          "affected": [v["variant_id"] for v in cond], "validity": "confirmed",
                          "mitigation": "SW 증가 · 통계(max)와 모델 오차를 줄이는 입력 확인 → " + LADDER_TEXT,
                          "checks": ["SW timing 통계(mean/max) · 증가 가정", "모델 total 오차 원인 rail", "여유 확보 lever (clock → compression → SW)"]})
        unreg = [v for v in verdicts if v["state"] not in ("uncovered", "na") and not v["registered"]]
        if unreg:
            risks.append({"key": "reference_unregistered", "rule": "reference_unregistered", "severity": "medium", "category": "전력",
                          "title": f"전과제 비교 기준 variant 미등록 {len(unreg)}건",
                          "detail": "; ".join(f"{_short(v['variant_id'])} "
                                              + (f"예측 {v['pred_mw']:.0f} mW ({v['pred_pct']:+.1f}%)" if v.get('pred_mw') is not None
                                                 else f"실측 {v['meas_mw']:.0f} mW ({v['meas_pct']:+.1f}%) · 비교 가능한 예측 없음") for v in unreg[:3]),
                          "affected": [v["variant_id"] for v in unreg], "validity": "confirmed",
                          "mitigation": "등록 차단 사유(SW > period · clock 상한) 해소 후 등록",
                          "checks": ["미등록 사유 (spec · 검증)", "등록 후 보고서 재생성"]})
        missing = [v["variant_id"] for v in verdicts if v["state"] in ("uncovered", "na") and v["variant_id"] not in kpi_gap]
        if missing:
            risks.append({"key": "reference_missing", "rule": "reference_missing", "severity": "high", "category": "전력",
                          "title": f"전과제 비교 기준 variant 판정 불가 {len(missing)}/{len(verdicts)}",
                          "detail": f"{_names(missing)} — 탐색 결과 없음 · 전과제 대비 전류 판정 불가", "affected": missing,
                          "validity": "confirmed", "mitigation": "조합 탐색에 포함해 예측 등록 후 보고서 재생성",
                          "checks": ["해당 scenario 조합 탐색", "예측 등록"]})
    else:  # legacy snapshots (no frozen references): previous rules
        over_rows = [r for r in ctx.get("rows") or [] if (r.get("reference") or {}).get("status") == "over"]
        if over_rows:
            over_rows.sort(key=lambda r: -(r["reference"].get("delta_pct") or 0))
            risks.append({"key": "power_over_reference", "rule": "power_over_reference", "severity": "high", "category": "전력",
                          "title": f"전과제 대비 전력 초과 {len(over_rows)}건",
                          "detail": ", ".join(f"{_short(r['variant_id'])} {r['total_mw']:.0f} mW ({r['reference']['delta_pct']:+.1f}%)" for r in over_rows[:4]),
                          "affected": [r["variant_id"] for r in over_rows], "mitigation": LADDER_TEXT, "checks": _POWER_CHECKS})
        ref = snap.get("reference_check") or {}
        missing = ref.get("missing") or []
        if missing:
            risks.append({"key": "reference_missing", "rule": "reference_missing", "severity": "high", "category": "전력",
                          "title": f"전과제 비교 기준 variant 예측 없음 {len(missing)}/{ref.get('total', len(missing))}",
                          "detail": f"{_names(missing)} — 전과제 대비 전류 판정 불가", "affected": missing,
                          "mitigation": "조합 탐색에 포함해 예측 등록 후 보고서 재생성", "checks": ["해당 scenario 조합 탐색", "예측 등록"]})

    if uncovered:
        refs = set(snap.get("references") or {})
        watch = {i["variant_id"] for i in (snap.get("thermal") or {}).get("items") or []}
        also = [x for x, on in (("전과제 기준", any(k["variant_ref"] in refs for k in uncovered)),
                                ("발열 감시", any(k["variant_ref"] in watch for k in uncovered))) if on]
        risks.append({"key": "kpi_uncovered", "rule": "kpi_uncovered", "severity": "high", "category": "coverage",
                      "title": f"KPI scenario 미탐색 {len(uncovered)}/{len(board)}",
                      "detail": ", ".join(str(k["label"]) for k in uncovered[:5]) + " — 예측 없음"
                      + (f" ({' · '.join(also)} 대상 — 전과제 판정 · 발열 평가 불가)" if also else ""),
                      "affected": [k["variant_ref"] for k in uncovered], "validity": "confirmed",
                      "mitigation": "KPI scenario를 조합 탐색에 포함해 예측 등록",
                      "checks": ["scenario 정의 · 입력 확인", "조합 탐색 · 등록"]})

    thermal = snap.get("thermal") or {}
    for pct, sev in ((10, "high"), (20, "medium")):
        # a −20 % miss only adds information when −10 % is reachable (otherwise the −10 % risk already covers it)
        short = [i for i in thermal.get("items") or [] if any(p["ask_pct"] == pct and not p["achieved"] for p in i.get("plans") or [])
                 and (pct == 10 or all(p["achieved"] for p in i.get("plans") or [] if p["ask_pct"] < pct))]
        if short:
            det = "; ".join(f"{_short(i['variant_id'])} 필요 {next(p['need_mw'] for p in i['plans'] if p['ask_pct'] == pct):.0f} mW, "
                            f"가능 최대 {next(p['saving_mw'] for p in i['plans'] if p['ask_pct'] == pct):.0f} mW" for i in short[:3])
            risks.append({"key": f"thermal_{pct}", "rule": "thermal_unreachable", "severity": sev, "category": "발열",
                          "title": f"발열 대응 −{pct}% 미달 {len(short)}건 (화질 열화 option 포함해도 부족)", "detail": det,
                          "affected": [i["variant_id"] for i in short], "validity": "confirmed",
                          "mitigation": LADDER_TEXT + " — 그래도 부족하면 성능 조건(해상도 · fps · EIS) 협의",
                          "checks": ["clock level 하향 여지", "compression 적용 buffer", "SW · CPU 배치 절감", "IQ 평가 대상 option",
                                     "성능 조건 trade 후보"]})
    unassessed = [i["variant_id"] for i in thermal.get("items") or [] if i.get("current_mw") is None and i["variant_id"] not in kpi_gap]
    if unassessed:
        risks.append({"key": "thermal_unassessed", "rule": "thermal_unassessed", "severity": "medium", "category": "발열",
                      "title": f"발열 감시 variant 미평가 {len(unassessed)}건", "detail": f"{_names(unassessed)} — 조합 탐색 결과 없음",
                      "affected": unassessed, "validity": "confirmed", "mitigation": "power option을 켜고 조합 탐색 실행",
                      "checks": ["조합 탐색 (power option 포함)"]})

    # SW-01: every spec-ok scenario counts, not only the Top-5 table (legacy snapshots: Top-5 only)
    if snap.get("scenarios"):
        low_rows = sorted((r for r in snap["scenarios"] if r.get("spec_ok") and r.get("sw_margin_pct") is not None
                           and r["sw_margin_pct"] < LOW_MARGIN_PCT), key=lambda r: r["sw_margin_pct"])
        low = [{"variant_id": r["variant_id"], "margin_pct": r["sw_margin_pct"], "stage": r.get("sw_stage"), "bottleneck": r.get("sw_bottleneck"),
                "assumed": (r.get("inputs") or {}).get("sw_timing_source") == "assumed"} for r in low_rows]
    else:
        low = [m for m in snap.get("sw_margin_top5") or [] if m.get("margin_pct") is not None and m["margin_pct"] < LOW_MARGIN_PCT]
    if low:
        m0 = low[0]
        neg = sum(1 for m in low if m["margin_pct"] < 0)
        tasks: dict[str, int] = {}
        for m in low:
            tasks[str(m.get("bottleneck"))] = tasks.get(str(m.get("bottleneck")), 0) + 1
        assumed = all(m.get("assumed") for m in low) if "assumed" in m0 else False
        risks.append({"key": "sw_margin_low", "rule": "sw_margin_low", "severity": "medium", "category": "SW",
                      "title": f"SW timing margin < {LOW_MARGIN_PCT:.0f}% · {len(low)}건" + (f" (음수 {neg})" if neg else ""),
                      "detail": f"최소 {m0['margin_pct']:.1f}% ({_short(m0['variant_id'])}, {str(m0.get('stage', '')).upper()}, 병목 {m0.get('bottleneck')})"
                      + " · 병목 " + ", ".join(f"{t} {n}" for t, n in sorted(tasks.items(), key=lambda kv: -kv[1])[:3])
                      + (" · SW timing 가정값" if assumed else ""),
                      "affected": [m["variant_id"] for m in low], "validity": "input_unverified" if assumed else "confirmed",
                      "mitigation": f"{m0.get('bottleneck')} 최적화 · HW offload · MID cluster 분산 배치 (CPU what-if)",
                      "checks": ["전과제 semantic Perfetto runtime · latency 분포", "SW 증가 예산 적용 시 CPU OPP 상향 여부",
                                 "병렬 instance 수 (pipelined 전제)"]})

    low_cpu = [c for c in snap.get("cpu") or [] if (c.get("summary") or {}).get("tolerance") is not None
               and c["summary"]["tolerance"] < CPU_TOLERANCE_MIN]
    if low_cpu:
        c0 = min(low_cpu, key=lambda c: c["summary"]["tolerance"])
        sm = c0["summary"]
        step = sm.get("opp_step") or {}
        risks.append({"key": "cpu_growth_tolerance", "rule": "cpu_growth_tolerance", "severity": "medium", "category": "CPU",
                      "title": f"SW 증가 허용치 < ×{CPU_TOLERANCE_MIN:.1f} · {len(low_cpu)}건",
                      "detail": f"최소 ×{sm['tolerance']:.2f} ({_short(c0['variant_id'])}, "
                                + ("timing 여유 소진" if sm.get("binding") == "timing" else
                                   f"{step.get('cluster')} OPP {step.get('mhz', ['?', '?'])[0]}→{step.get('mhz', ['?', '?'])[1]} MHz {step.get('delta_mw', 0):+.0f} mW")
                                + ")",
                      "affected": [c["variant_id"] for c in low_cpu], "validity": "confirmed",
                      "mitigation": "SW 증가 예산 합의 · task offload / 전용 core · cluster 재배분 (CPU what-if)",
                      "checks": ["SW 증가 예산", "cluster 재배분 결과"]})

    # the remaining power saving needs IQ evaluation: clock · compression · SW first (lever ladder)
    opts = snap.get("power_options") or []
    gated = [o for o in opts if (o.get("best") or {}).get("iq_eval") == "required"]
    if opts and gated and len(gated) == len([o for o in opts if o.get("best")]):
        adopted = [o for o in gated if (o.get("best") or {}).get("review_status") == "adopted"]
        risks.append({"key": "iq_gated_saving", "rule": "iq_gated_saving", "severity": "medium", "category": "화질",
                      "title": f"추가 절감안 {len(gated)}/{len(opts)}이 화질 열화 option (IQ 평가 대상)",
                      "detail": f"승인(adopted) {len(adopted)} · 대기 {len(gated) - len(adopted)} — "
                                + ", ".join(sorted({' + '.join(o['best'].get('labels') or []) for o in gated})[:2]),
                      "affected": [o["variant_id"] for o in gated], "validity": "confirmed",
                      "mitigation": "화질 열화 option은 최후 수단 — " + LADDER_TEXT,
                      "checks": ["clock 최소 level 확인", "lossless compression · LLC 적용 여지", "SW 최적화 · CPU 배치",
                                 "부족분에 한해 IQ 평가 계획"]})

    model = snap.get("model") or {}
    common = [(c, b) for c, b in (model.get("bias") or {}).items() if c != "total" and b.get("verdict") == "model_common"]
    if common or model.get("offsetting"):
        parts = [f"{c.upper()} {b['median']:+.0f}%" for c, b in common]
        risks.append({"key": "model_bias", "rule": "model_bias", "severity": "medium", "category": "모델",
                      "title": "예측 모델 공통 오차" + (f": {' · '.join(parts)}" if parts else ""),
                      "detail": (f"구성 median Δ {', '.join(parts)} (같은 방향 ≥ 80%)" if parts else "")
                      + (f"{' · ' if parts else ''}total ±10% 이내 중 상쇄 {model.get('offsetting')}건" if model.get("offsetting") else ""),
                      "affected": [], "validity": "confirmed", "mitigation": "Power fit으로 구성 계수 보정 · CPU 모델 profile 전환 검토",
                      "checks": ["Power fit 보정 preview", "rail별 오차 drill-down"]})

    sample = []
    if ov.get("sample_dvfs"):
        sample.append(f"DVFS table SAMPLE ({ov.get('dvfs_table_ref')})")
    origin = (model.get("coverage") or {}).get("origin") or {}
    if model and not origin.get("physical_capture"):
        sample.append(f"실측 대조 silicon capture 없음 (합성 {origin.get('synthetic', 0)}건)")
    if sample:
        risks.append({"key": "sample_input", "rule": "sample_input", "severity": "info", "category": "데이터",
                      "title": "SAMPLE 입력 · 실측 근거 부족", "detail": " · ".join(sample), "affected": [], "validity": "confirmed",
                      "mitigation": "사내 DVFS table · silicon capture로 교체", "checks": ["사내 DVFS table", "silicon capture import"]})
    # REF-04: a spec upgrade over the previous project with no power headroom left
    up = [v for v in verdicts if v.get("spec_up") and v["state"] in ("over", "conditional")]
    if up:
        risks.append({"key": "spec_up_no_headroom", "rule": "spec_up_no_headroom", "severity": "high", "category": "전력",
                      "title": f"전과제 대비 spec 상향인데 전력 여유 없음 {len(up)}건",
                      "detail": "; ".join(f"{_short(v['variant_id'])} {', '.join(v['spec_up'])} · {STATE_LABEL[v['state']]}" for v in up[:3]),
                      "affected": [v["variant_id"] for v in up], "validity": "confirmed",
                      "mitigation": "상향 spec의 전력 예산 합의 → " + LADDER_TEXT,
                      "checks": ["상향 항목별 증가분 (증감 분해)", "clock · compression 여지", "spec 상향 범위 재협의"]})
    diffs = [v for v in verdicts if v.get("cond_diff") and not v.get("spec_up")]
    if diffs:
        risks.append({"key": "reference_condition_diff", "rule": "reference_condition_diff", "severity": "medium", "category": "전력",
                      "title": f"전과제 비교 조건 차이 {len(diffs)}건 — 판정은 참고",
                      "detail": "; ".join(f"{_short(v['variant_id'])} " + ", ".join(f"{d['key']} {d['prev']}→{d['cur']}" for d in v["cond_diff"][:3])
                                          for v in diffs[:3]),
                      "affected": [v["variant_id"] for v in diffs], "validity": "confirmed",
                      "mitigation": "같은 조건의 전과제 variant로 mapping (power_reference.mapping) 또는 조건 차이를 판정에 반영",
                      "checks": ["조건 차이 항목 확인", "mapping 지정"]})
    # SW-03: the SW growth the next project must absorb (policy sw_growth_budget)
    budget = ((snap.get("review_context") or {}).get("policy") or {}).get("sw_growth_budget")
    if budget and snap.get("scenarios"):
        short_g = [r for r in snap["scenarios"] if r.get("spec_ok") and (r.get("sw") or {}).get("growth_tolerance") is not None
                   and float(r["sw"]["growth_tolerance"]) < float(budget) - 1e-6]
        if short_g:
            r0 = min(short_g, key=lambda r: r["sw"]["growth_tolerance"])
            risks.append({"key": "sw_growth_budget", "rule": "sw_growth_budget", "severity": "medium", "category": "SW",
                          "title": f"SW 증가 예산 ×{float(budget):.1f} 흡수 불가 {len(short_g)}건",
                          "detail": f"최소 ×{float(r0['sw']['growth_tolerance']):.2f} ({_short(r0['variant_id'])}, 병목 {r0.get('sw_bottleneck')})",
                          "affected": [r["variant_id"] for r in short_g],
                          "validity": "input_unverified" if all((r.get("inputs") or {}).get("sw_timing_source") == "assumed" for r in short_g) else "confirmed",
                          "mitigation": "clock 1 level 상향 비용 확인 → SW 최적화 · CPU 배치 (CPU what-if)",
                          "checks": ["증가 시 필요 DVFS level · ΔmW", "병목 task 최적화 여지", "SW 증가 예산 재합의"]})
    dq = data_quality(snap)
    if any(d["level"] in ("warn",) for d in dq):
        w = [d for d in dq if d["level"] == "warn"]
        risks.append({"key": "data_quality", "rule": "data_quality", "severity": "info", "category": "데이터",
                      "title": f"입력 데이터 확인 필요 {len(w)}건", "detail": "; ".join(d["text"] for d in w[:3]),
                      "affected": sorted({v for d in w for v in d["variants"]}), "validity": "confirmed",
                      "mitigation": "입력 정정 후 재탐색", "checks": [d["check"] for d in w[:3]]})
    for r in risks:  # RISK-01: Critical only for confirmed findings
        r.setdefault("validity", "confirmed")
        r.setdefault("checks", [])
        if r["severity"] == "critical" and r["validity"] != "confirmed":
            r["severity"] = "high"
    from scenario_db.reporting.review_verdict import _DECISION  # noqa: PLC0415

    for r in risks:  # RISK-02 / RISK-03
        r["priority"] = risk_priority(r, snap)
        r["decision_needed"] = r["key"] in _DECISION
    risks.sort(key=lambda r: (SEVERITY_ORDER[r["severity"]], -r["priority"]))
    return risks


_POWER_CHECKS = ["필요 clock 최소 level 여부 (DVFS)", "lossless compression · LLC 적용 여지", "SW · CPU 배치 절감", "화질 열화 option (최후 · IQ 평가)"]


def risk_counts(register: list[dict[str, Any]]) -> dict[str, int]:
    """Open (not closed / accepted) risks per severity — the Portfolio cell."""
    out = {k: 0 for k in SEVERITY_ORDER}
    for r in register:
        if r.get("status") not in ("closed", "accepted") and r.get("auto_state") != "resolve_candidate":
            out[r["severity"]] = out.get(r["severity"], 0) + 1
    return out
