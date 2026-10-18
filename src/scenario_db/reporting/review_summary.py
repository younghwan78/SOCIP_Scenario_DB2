"""Tier 0 — one-page summary of a project report (UX-01, COV-01..03).

Conditions strip · scenario coverage · KPI scoreboard · three messages · top risks with what to check first ·
decisions requested · the power-saving order. Everything is read from the frozen snapshot.
"""

from __future__ import annotations

from html import escape
from typing import Any

from scenario_db.reporting.review_verdict import (
    GLOSSARY,
    LADDER,
    STATE_LABEL,
    VALIDITY_LABEL,
    data_quality,
    decisions,
    drivers,
    growth_budget_state,
    lever_actions,
    messages,
    power_verdicts,
    scoreboard,
    short,
)

_SEV = {"critical": ("Critical", "fail"), "high": ("High", "fail"), "medium": ("Medium", "warn"), "info": ("Info", "mute")}
_IQ = {"adopted": ("IQ 승인", "ok"), "iq_eval": ("IQ 평가 중", "warn"), "candidate": ("IQ 대기", "warn"),
       "rejected": ("IQ 반려", "mute"), "not_required": ("IQ 영향 없음", "ok")}

TIER0_CSS = """
.t0 .strip{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));border:1px solid #EFEAE1;border-radius:8px;overflow:hidden;margin:8px 0}
.t0 .strip>div{padding:7px 10px;border-right:1px solid #EFEAE1;display:grid;gap:1px;min-width:0}
.t0 .strip .k{font-size:11.5px;color:#8A8274;font-weight:600}.t0 .strip .v{font-size:14px;font-weight:600;overflow-wrap:anywhere}
.t0 .strip .s{font-size:12px;color:#7A7468;overflow-wrap:anywhere}
.t0 .cov{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 10px}
.t0 .cov span{font-size:12.5px;border:1px solid #E4DED3;border-radius:6px;padding:2px 8px;background:#FBFAF7}
.t0 .cov span.on{border-color:#9CC3BA;background:#E3EEEB;color:#174D47}.t0 .cov span.off{color:#7A7468}
.pill{display:inline-block;font-size:12px;font-weight:600;padding:1px 8px;border-radius:999px;white-space:nowrap}
.pill.ok{background:#E3EEEB;color:#1E5A53}.pill.warn{background:#FCEFD6;color:#7A4B12}.pill.org{background:#FBE4CF;color:#8A3D0C}
.pill.fail{background:#F8E1DE;color:#8A2420}.pill.mute{background:#EFEAE2;color:#5E584C}
.t0 ol.msg{margin:6px 0 10px 20px;padding:0}.t0 ol.msg li{margin:3px 0;font-size:15px}
.t0 .two{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:14px}
.t0 .dec{border:1px dashed #9CC3BA;border-radius:8px;padding:10px 12px}.t0 .dec b{color:#174D47}
.t0 .ladder{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}.t0 .ladder span{font-size:12.5px;padding:2px 8px;border-radius:6px;background:#F4F8F6}
.t0 .ladder span.last{background:#FBE4CF;color:#8A3D0C}
@media(max-width:1100px){.t0 .strip{grid-template-columns:repeat(2,minmax(0,1fr))}.t0 .two{grid-template-columns:1fr}}
@media print{section.tier0{break-after:page}}
"""


def _p(label: str, cls: str) -> str:
    return f"<span class='pill {cls}'>{escape(label)}</span>"


def _mw(v: Any) -> str:
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def conditions_strip(pc: dict[str, Any] | None) -> str:
    if not pc:
        return ""
    sw = pc.get("sw_timing_source") or {}
    n = sum(sw.values())
    sw_txt = " · ".join(f"{'가정값' if k == 'assumed' else k} {v}/{n}" for k, v in sorted(sw.items(), key=lambda kv: -kv[1])) or "—"
    ref = pc.get("reference") or {}
    srcs = ref.get("sources") or {}
    names = {"explicit": "지정값", "measurement": "실측", "prediction": "예측", "synthetic": "합성"}
    ref_txt = " · ".join(f"{names.get(k, k)} {v}" for k, v in srcs.items()) or "없음"
    growth = pc.get("sw_growth") or 1.0
    budget = pc.get("sw_growth_budget")
    cells = [
        ("SoC", pc.get("soc_name"), pc.get("soc_ref")),
        ("Board", pc.get("board_name") or pc.get("board_type"), pc.get("board_type")),
        ("Sensor · Display", short(str(pc.get("sensor_module_ref") or "—")), str(pc.get("display_module_ref") or "")),
        ("SW", str(pc.get("sw_profile_ref") or "—"), f"timing {sw_txt} · 증가 ×{float(growth):.1f}"
         + (f" (예산 ×{float(budget):.1f})" if budget else "")),
        ("DVFS", str(pc.get("dvfs_table_ref") or "—"), "SAMPLE · 사내 table 아님" if pc.get("sample_dvfs") else "사내 table"),
        ("전과제 기준", ref.get("project_ref") or ("지정값" if srcs else "없음"),
         f"{ref_txt} · 허용 +{ref.get('tolerance_pct') if ref.get('tolerance_pct') is not None else '—'}%"),
    ]
    return "<div class='strip'>" + "".join(
        f"<div><span class='k'>{escape(k)}</span><span class='v'>{escape(str(v or '—'))}</span><span class='s'>{escape(str(s or ''))}</span></div>"
        for k, v, s in cells) + "</div>"


def coverage_strip(cov: dict[str, Any] | None) -> str:
    if not cov or not cov.get("rows"):
        return ""
    tot = cov.get("total") or {}
    spans = []
    for r in sorted(cov["rows"], key=lambda r: (-r["explored"], r["name"])):
        on = r["explored"] > 0
        spans.append(f"<span class='{'on' if on else 'off'}'>{escape(r['name'])} <b>{r['explored']}</b>"
                     + (f" · 등록 {r['registered']}" if on else "") + f" / {r['variants']}</span>")
    note = (f"제품 variant {tot.get('variants', 0)} 중 탐색 {tot.get('explored', 0)} · 등록 {tot.get('registered', 0)} · "
            f"실측 {tot.get('measured', 0)} (silicon {tot.get('measured_physical', 0)}) · 실측 있으나 예측 없음 {tot.get('measured_no_prediction', 0)}"
            + (f" · 파생 sub-variant {tot.get('derived')} 제외" if tot.get("derived") else ""))
    return f"<p class=meta>Scenario coverage (탐색 · 등록 / 제품 variant) — {escape(note)}</p><div class='cov'>{''.join(spans)}</div>"


def _verdict_cell(v: dict[str, Any] | None) -> str:
    if v is None:
        return "<span class=meta>기준 없음</span>"
    if v["state"] == "uncovered":
        return f"<span class=meta>기준 {_mw(v['ref_mw'])} · 판정 불가</span>"
    parts = [f"예측 {v['pred_pct']:+.1f}%" if v.get("pred_pct") is not None else "예측 —"]
    if v.get("meas_pct") is not None:
        parts.append(f"<b>{'실측' if v['basis'] == 'measurement' else '합성 실측'} {v['meas_pct']:+.1f}%</b>")
    if v.get("band_pct") and v["band_pct"][1] is not None and v["state"] == "conditional":
        parts.append(f"범위 상단 {v['band_pct'][1]:+.1f}%")
    if v.get("corr_pct") is not None and v["state"] == "conditional":
        parts.append(f"보정 {v['corr_pct']:+.1f}%")
    if not v.get("registered"):
        parts.append("<b>미등록</b>")
    return " · ".join(parts) + f"<div class=meta>기준 {_mw(v['ref_mw'])} mW ({escape(str(v.get('ref_source') or ''))})</div>"


def kpi_table(board: list[dict[str, Any]], budget: float | None = None) -> str:
    if not board:
        return "<p class=meta>KPI scenario 없음 — review_policy.kpi 또는 thermal_watch · power_reference를 설정하세요</p>"
    h = ("<table><tr><th>KPI</th><th>fps</th><th>전력 예측 mW (탐색 범위)</th><th>전과제 대비</th><th>SW 여유 (증가 허용)</th><th>화질 (IQ)</th><th>종합</th></tr>")
    for k in board:
        fps = k["fps"]
        pw = k.get("power") or {}
        band = pw.get("band")
        pw_txt = (f"{_mw(pw.get('mw'))}" + (f" <span class=meta>({_mw(band[0])}–{_mw(band[1])})</span>" if band else "")
                  + ("" if k.get("registered", True) else " <span class=meta>미등록</span>")) if pw.get("mw") is not None else "—"
        sw = k.get("sw_margin_pct")
        sw_txt = (f"<span class='{'fail' if sw < 0 else 'warn' if sw < 10 else ''}'>{sw:+.0f}%</span>" if sw is not None else "—")
        g = k.get("sw_growth_tolerance")
        if g is not None:
            low = budget is not None and float(g) < float(budget) - 1e-6
            sw_txt += f"<div class='meta {'fail' if low else ''}'>증가 허용 ×{float(g):.2f}</div>"
        iq = k.get("iq")
        iq_txt = "—"
        if iq:
            lbl, cls = _IQ.get(str(iq["status"]), (str(iq["status"]), "mute"))
            iq_txt = f"절감안 {_mw(iq.get('saving_mw'))} mW {_p(lbl, cls)}"
        ov = k["overall"]
        h += (f"<tr><td><b>{escape(str(k['label']))}</b><div class=meta>{escape(k.get('tier') or '')}</div></td>"
              f"<td>{_p(fps['label'], fps['cls'])}" + (f"<div class=meta>{escape(fps.get('why') or '')}</div>" if fps.get("why") else "") + "</td>"
              f"<td class=n>{pw_txt}</td><td>{_verdict_cell(k.get('verdict'))}</td><td class=n>{sw_txt}</td><td>{iq_txt}</td>"
              f"<td>{_p(ov['label'], ov['cls'])}</td></tr>")
    return h + "</table>"


def top_risks(reg: list[dict[str, Any]], n: int = 5) -> str:
    rows = [r for r in reg if r.get("status") not in ("closed", "accepted") and r.get("trend") != "resolve_candidate"][:n]
    if not rows:
        return "<p class=meta>열린 risk 없음</p>"
    h = "<table><tr><th>ID</th><th>심각도</th><th>내용</th><th>먼저 확인</th><th>Owner</th></tr>"
    for r in rows:
        lbl, cls = _SEV.get(r["severity"], (r["severity"], "mute"))
        val = r.get("validity") or "confirmed"
        h += (f"<tr><td class=mono>{escape(r['label'])}</td><td>{_p(lbl, cls)}"
              + (f" {_p(VALIDITY_LABEL.get(val, val), 'org')}" if val != "confirmed" else "") + "</td>"
              f"<td><b>{escape(r['title'])}</b><div class=meta>{escape(r.get('detail') or '')}</div></td>"
              f"<td class=meta>{escape(' → '.join((r.get('checks') or [])[:2]) or r.get('mitigation') or '—')}</td>"
              f"<td>{escape(r.get('owner') or '—')}" + (f"<div class=meta>{escape(str(r['due_date']))}</div>" if r.get("due_date") else "")
              + "</td></tr>")
    return h + "</table>"


def tier0(snap: dict[str, Any]) -> str:
    verdicts = power_verdicts(snap)
    board = scoreboard(snap, verdicts)
    msgs = messages(snap, board, verdicts)
    reg = snap.get("risk_register") or []
    risks = [r | {"key": r.get("key") or r.get("risk_key")} for r in reg if r.get("status") not in ("closed", "accepted")]
    dec = decisions(risks)
    conf = (snap.get("conclusion") or {}).get("confidence") or {}
    h = "<div class='t0'>"
    h += (f"<p class=meta>근거 등급 <b>{escape(str(conf.get('grade') or '—'))}</b> — {escape(str(conf.get('meaning') or ''))}"
          + (f" ({escape('; '.join(conf.get('reasons') or []))})" if conf.get("reasons") else "") + "</p>")
    h += conditions_strip(snap.get("project_conditions")) + coverage_strip(snap.get("coverage"))
    budget = (((snap.get("review_context") or {}).get("policy") or {}).get("sw_growth_budget"))
    h += ("<h3 style='margin:10px 0 4px'>KPI scenario</h3>" + kpi_table(board, budget)
          + (f"<p class=meta>SW 증가 예산 ×{float(budget):.1f} — 증가 허용이 예산보다 작으면 빨간색 (DVFS 재선택 포함 timing 유지 한계)</p>" if budget else ""))
    blk = [d for d in data_quality(snap) if d["level"] == "block"]
    if blk:
        h += "<p class=fail style='font-size:13.5px'>게시 전 확인 필요: " + escape(" · ".join(d["text"] for d in blk)) + "</p>"
    h += "<ol class='msg'>" + "".join(f"<li>{escape(m)}</li>" for m in msgs) + "</ol>"
    h += ("<div class='two'><div><h3 style='margin:4px 0'>Top risk</h3>" + top_risks(reg) + "</div>"
          "<div class='dec'><b>결정 요청</b>"
          + ("<ol style='margin:4px 0 0 18px;padding:0'>" + "".join(f"<li>{escape(d)}</li>" for d in dec) + "</ol>" if dec
             else "<p class=meta>없음</p>")
          + "<p class=meta style='margin-top:8px'>전력 절감 검토 순서</p><div class='ladder'>"
          + "".join(f"<span class='{'last' if k == 4 else ''}'>{escape(v[1])}</span>" for k, v in LADDER.items())
          + "</div></div></div>")
    return h + "</div>"


def glossary() -> str:
    return ("<h3 style='margin:14px 0 4px'>용어</h3><table><tr><th>용어</th><th>뜻</th></tr>"
            + "".join(f"<tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in GLOSSARY) + "</table>")


def verdict_table(snap: dict[str, Any]) -> str:
    """Tier 2 power section: every previous-project comparison with its evidence."""
    vs = power_verdicts(snap)
    if not vs:
        return ""
    h = ("<h3 style='margin:12px 0 4px'>전과제 대비 판정 — 예측 · 탐색 범위 · 보정 예측 · 실측</h3>"
         "<p class=meta>실측(silicon)이 있으면 실측으로 판정하고 예측과 반대면 불일치로 표시. 예측이 이하여도 탐색 범위 상단 · 보정 예측 · 합성 실측이 "
         "허용을 넘으면 조건부.</p><table><tr><th>Variant</th><th>기준 mW</th><th>예측 mW</th><th>탐색 범위</th><th>보정 예측</th><th>실측</th>"
         "<th>판정</th><th>근거</th></tr>")
    cls = {"over": "fail", "conditional": "org", "similar": "warn", "ok": "ok", "na": "mute", "uncovered": "mute"}
    for v in vs:
        band = v.get("band_mw")
        pp = "" if v.get("pred_pct") is None else f"{v['pred_pct']:+.1f}%"
        cp = "" if v.get("corr_pct") is None else f" <span class=meta>{v['corr_pct']:+.1f}%</span>"
        mp = "" if v.get("meas_pct") is None else f" <span class=meta>{v['meas_pct']:+.1f}% · {escape(str(v.get('meas_origin') or ''))}</span>"
        band_txt = f"{_mw(band[0])}–{_mw(band[1])}" if band else "—"
        state = ("불일치 · " if v.get("flip") else "") + STATE_LABEL[v["state"]]
        h += (f"<tr><td>{escape(short(v['variant_id']))}</td><td class=n>{_mw(v['ref_mw'])} <span class=meta>{escape(str(v.get('ref_source') or ''))}</span></td>"
              f"<td class=n>{_mw(v.get('pred_mw'))}{'' if v.get('registered') else ' <span class=meta>미등록</span>'} <span class=meta>{pp}</span></td>"
              f"<td class=n>{band_txt}</td><td class=n>{_mw(v.get('corr_mw'))}{cp}</td><td class=n>{_mw(v.get('meas_mw'))}{mp}</td>"
              f"<td>{_p(state, 'fail' if v.get('flip') else cls[v['state']])}</td>"
              f"<td class=meta>{escape(v.get('why') or '')}</td></tr>")
    bias = next((v.get("bias_pct") for v in vs if v.get("bias_pct") is not None), None)
    return h + "</table>" + (f"<p class=meta>보정 예측 = 예측 ÷ (1 {bias:+.1f}%) — 실측 대조 total median 오차</p>" if bias is not None else "")


def ladder_table(snap: dict[str, Any]) -> str:
    """Power-saving candidates in the order a project applies them (clock → compression → SW → IQ-degrading last)."""
    acts = lever_actions(snap, limit_per_tier=4)
    if not acts:
        return ""
    h = ("<h3 style='margin:12px 0 4px'>전력 절감 검토 순서</h3><p class=meta>최적 clock 설정 → compression 활용 → SW 최적화를 먼저, "
         "화질을 열화시키는 option(MTNR L0 skip · LowPower 등)은 마지막. ΔmW = 후보별 최대(clock · option) 또는 variant 평균(compression).</p>"
         "<table><tr><th>순서</th><th>후보</th><th>대상</th><th>ΔmW</th><th>근거</th><th>확인</th></tr>")
    for a in acts:
        t = a["targets"]
        tgt = (", ".join(short(x) for x in t[:3]) + (f" 외 {len(t) - 3}" if len(t) > 3 else "")) if t else "—"
        h += (f"<tr><td class=meta>{escape(LADDER[a['tier']][1])}</td><td>{escape(a['action'])}</td><td class=meta>{escape(tgt)}</td>"
              f"<td class=n>{_mw(a['delta_mw']) if a['delta_mw'] is not None else '—'}</td><td class=meta>{escape(a['basis'])}</td>"
              f"<td class='{'warn' if a['iq'] else ''}'>{escape(a['check'])}</td></tr>")
    tiers = {a["tier"] for a in acts}
    missing = [LADDER[k][1] for k in (1, 2, 3) if k not in tiers]
    return h + "</table>" + (f"<p class=meta>후보 없음: {escape(' · '.join(missing))} — 해당 단계 여지는 탐색 결과에 없음 "
                             "(clock은 이미 필요 최소 level, compression은 지원 buffer 적용 완료 등)</p>" if missing else "")


def drivers_table(snap: dict[str, Any]) -> str:
    """RISK-04: the causes behind the open risks — where to look first."""
    ds = drivers(snap)
    if not ds:
        return ""
    return ("<h3 style='margin:4px 0'>원인 driver — 어디를 먼저 볼 것인가</h3><table><tr><th>Driver</th><th>영향 variant</th><th>내용</th><th>먼저 확인</th></tr>"
            + "".join(f"<tr><td><b>{escape(d['label'])}</b></td><td class=n>{d['count']} / {d['total']}</td><td class=meta>{escape(d['note'])}</td>"
                      f"<td>{escape(d['check'])}</td></tr>" for d in ds) + "</table>")


def decomp_table(snap: dict[str, Any]) -> str:
    """REF-02/03/04: what changed against the previous project — conditions, CPU / IP / BW split, latency."""
    vs = [v for v in power_verdicts(snap) if v.get("state") not in ("uncovered",)]
    rich = [v for v in vs if v.get("decomp") or v.get("cond_diff") is not None or v.get("latency_delta_frames") is not None]
    if not vs:
        return ""
    if not rich:
        return ("<p class=meta>전과제 증감 분해 · 조건 비교 불가 — 기준이 지정값(총합)뿐. review_policy.power_reference.project_ref로 "
                "전과제를 지정하면 CPU · IP · BW 분해, 조건 차이, latency 변화가 표시됩니다.</p>")
    h = ("<h3 style='margin:12px 0 4px'>전과제 대비 증감 분해 · 조건 · 성능</h3><p class=meta>분해 = 현재 예측 − 전과제 예측(구성별). "
         "기준 차이 = 전과제 예측 총합 − 기준값(실측 등). Δ CPU/IP/BW와 더하면 현재 예측 − 기준값. 조건 차이가 있으면 판정은 참고.</p>"
         "<table><tr><th>Variant</th><th>Δ CPU</th><th>Δ IP</th><th>Δ BW</th><th>기준 차이</th><th>조건 차이</th><th>spec 상향</th><th>Δ latency (frame)</th></tr>")
    for v in rich:
        d = v.get("decomp") or {}
        cell = lambda k: (f"<td class='n {'fail' if (d.get(k) or 0) > 0.5 else 'ok' if (d.get(k) or 0) < -0.5 else ''}'>{d[k]:+.1f}</td>"  # noqa: E731
                          if d.get(k) is not None else "<td class=n>—</td>")
        cd = v.get("cond_diff")
        cd_txt = "같음" if cd == [] else "—" if cd is None else ", ".join(f"{x['key']} {x['prev']}→{x['cur']}" for x in cd[:4])
        lat = v.get("latency_delta_frames")
        h += (f"<tr><td>{escape(short(v['variant_id']))}" + (f" <span class=meta>← {escape(short(v['prev_variant']))}</span>" if v.get("prev_variant") else "")
              + "</td>" + cell("CPU") + cell("IP") + cell("BW") + cell("기준 차이")
              + f"<td class=meta>{escape(cd_txt)}</td><td>{escape(', '.join(v.get('spec_up') or [])) or '—'}</td>"
              + f"<td class=n>{'—' if lat is None else f'{lat:+.2f}'}</td></tr>")
    return h + "</table>"


def sw_table(snap: dict[str, Any]) -> str:
    """SW-02/03: stage time vs frame period (frames in flight), longest SW task, SW growth the budget asks for."""
    budget = (((snap.get("review_context") or {}).get("policy") or {}).get("sw_growth_budget"))
    kpi = {k["variant_ref"]: k["label"] for k in scoreboard(snap)}
    rows = [r for r in snap.get("scenarios") or [] if r.get("spec_ok") and r.get("sw") and r["sw"].get("hw_ms") is not None
            and (r["variant_id"] in kpi or (r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < 10))]
    if not rows:
        return ""
    rows.sort(key=lambda r: (r["variant_id"] not in kpi, r.get("sw_margin_pct") if r.get("sw_margin_pct") is not None else 999))
    scales = sorted({g["scale"] for r in rows for g in r["sw"].get("growth") or []})
    h = ("<h3 style='margin:12px 0 4px'>SW timing — stage 시간 · 병렬 처리 · SW 증가</h3><p class=meta>stage 시간 = HW + SW (최소 여유 stage). "
         "frame 주기를 넘으면 그 수만큼 frame이 동시에 처리되어야 fps 유지(pipelined). 증가 허용 = DVFS 재선택 포함 timing 유지 한계 (≥ = 탐색한 최대 배율까지 유지)"
         + (f", 예산 ×{float(budget):.1f}" if budget else "") + ". 증가별 전력은 목적 통계 기준.</p>"
         "<table><tr><th>Variant</th><th>stage</th><th>HW + SW ms</th><th>frame ms</th><th>동시 frame</th><th>최장 task ms</th><th>여유</th><th>증가 허용</th>"
         + "".join(f"<th>×{s:.1f} mW</th>" for s in scales) + "</tr>")
    for r in rows[:25]:
        sw = r["sw"]
        g = sw.get("growth_tolerance")
        state = growth_budget_state(sw, budget)
        gm = {x["scale"]: x for x in sw.get("growth") or []}
        bn = "—" if sw.get("bottleneck_ms") is None else f"{float(sw['bottleneck_ms']):.1f}"
        capped = g is not None and sw.get("growth_tested_max") is not None and float(g) >= float(sw["growth_tested_max"]) - 1e-6
        gt = "—" if g is None else f"{'≥' if capped else ''}×{float(g):.2f}"
        h += (f"<tr><td>{escape(kpi.get(r['variant_id']) or short(r['variant_id']))}</td><td>{escape(str(sw.get('stage') or '').upper())}</td>"
              f"<td class=n>{float(sw.get('hw_ms') or 0):.1f} + {float(sw.get('sw_ms') or 0):.1f}</td><td class=n>{float(sw.get('period_ms') or 0):.2f}</td>"
              f"<td class=n>{sw.get('in_flight') or '—'}</td><td class=n>{bn}"
              f" <span class=meta>{escape(str(r.get('sw_bottleneck') or ''))}</span></td>"
              f"<td class='n {'fail' if (r.get('sw_margin_pct') or 0) < 0 else ''}'>{float(r.get('sw_margin_pct') or 0):+.0f}%</td>"
              f"<td class='n {'fail' if state == 'short' else 'warn' if state == 'unverified' else ''}'>{gt}"
              + (" · 예산까지 미검증" if state == "unverified" else "") + "</td>"
              + "".join(f"<td class='n {'' if (gm.get(s) or {}).get('ok', True) else 'fail'}'>{_mw((gm.get(s) or {}).get('total_mw'))}</td>" for s in scales)
              + "</tr>")
    return h + "</table>" + (f"<p class=meta>외 {len(rows) - 25}건 생략</p>" if len(rows) > 25 else "")


def dq_table(snap: dict[str, Any]) -> str:
    dq = data_quality(snap)
    if not dq:
        return "<p class=meta>입력 데이터 확인 항목 없음</p>"
    lv = {"block": ("게시 전 확인", "fail"), "warn": ("확인 필요", "warn"), "info": ("참고", "mute")}
    return ("<h3 style='margin:12px 0 4px'>입력 데이터 품질</h3><table><tr><th>수준</th><th>내용</th><th>확인</th></tr>"
            + "".join(f"<tr><td>{_p(*lv[d['level']])}</td><td>{escape(d['text'])}</td><td class=meta>{escape(d['check'])}</td></tr>" for d in dq)
            + "</table>")
