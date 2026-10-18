"""Tiered project review report (RPT-08 .. RPT-12).

Tier 1  결론 · Risk register · 이전 보고서 대비            (management: one page, what changed)
Tier 2  area sections, first line = the area's conclusion   (architect: 성능 · Power · Lever · CPU · 예측↔실측)
Tier 3  Scenario dossier, one fixed card per variant         (system engineer: everything about one variant)

All numbers come from the frozen snapshot; nothing here queries the database.
"""

from __future__ import annotations

from html import escape
from typing import Any

from scenario_db.reporting import arch_report as ar

_f, _short = ar._f, ar._short


TOP_N = 10


def _more(label: str, body: str) -> str:
    return f"<details class='more'><summary>{escape(label)} ▸</summary>{body}</details>"


def _lead(text: str, cls: str = "") -> str:
    return f"<p class='lead {cls}'>{text}</p>"


def _cls(v: float | None, ok: float = 10, warn: float = 25) -> str:
    if v is None:
        return ""
    return "ok" if abs(v) <= ok else "warn" if abs(v) <= warn else "fail"


def _gx(g: float | None) -> str:
    if g is None:
        return "—"
    r = round(float(g), 2)
    return f"×{r:.1f}" if abs(r * 10 - round(r * 10)) < 1e-6 else f"×{r:.2f}"


# ------------------------------------------------------------------- RPT-11
def previous_block(p: dict[str, Any] | None) -> str:
    if not p:
        return ""
    rep = p.get("report") or {}
    risks, pw = p.get("risks") or {}, p.get("power") or {}
    h = (f"<p class=meta>직전 과제 보고서 <span class=mono>{escape(str(rep.get('id', ''))[:16])}</span> · "
         f"{escape(str(rep.get('generated_at') or '')[:16].replace('T', ' '))} · {escape(str(rep.get('status') or ''))}</p>")
    lines = []
    if risks.get("new"):
        lines.append(f"<b class=fail>신규 risk {len(risks['new'])}</b>: {escape('; '.join(risks['new'][:4]))}")
    if risks.get("reopened"):
        lines.append(f"<b class=warn>재발 {len(risks['reopened'])}</b>: {escape('; '.join(risks['reopened'][:4]))}")
    if risks.get("resolved"):
        lines.append(f"<b class=ok>해소 후보 {len(risks['resolved'])}</b>: {escape('; '.join(risks['resolved'][:4]))}")
    if not lines:
        lines.append("risk 변화 없음")
    h += "<ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul>"
    if pw.get("changed"):
        h += (f"<h3 style='margin:10px 0 4px'>Power 변화 상위 (|Δ| ≥ 1 mW · {pw.get('changed_count')}건)</h3>"
              "<table><tr><th>Variant</th><th>직전 mW</th><th>현재 mW</th><th>Δ mW</th><th>Δ%</th></tr>"
              + "".join(f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['prev_mw'])}</td><td class=n>{_f(r['cur_mw'])}</td>"
                        f"<td class='n {'fail' if r['delta_mw'] > 0 else 'ok'}'>{r['delta_mw']:+.1f}</td><td class=n>{_f(r.get('delta_pct'))}%</td></tr>"
                        for r in pw["changed"]) + "</table>")
    else:
        h += "<p class=meta>등록 예측 power 변화 없음</p>"
    if pw.get("added") or pw.get("removed"):
        h += (f"<p class=meta>추가 variant {len(pw.get('added') or [])}: {escape(', '.join(_short(v) for v in (pw.get('added') or [])[:6]))}"
              f" · 제외 {len(pw.get('removed') or [])}: {escape(', '.join(_short(v) for v in (pw.get('removed') or [])[:6]))}</p>")
    label = {"fps_ok": "① fps 만족", "fps_total": "평가 variant", "power_ok": "② 전과제 이하", "power_similar": "② 유사",
             "power_over": "② 초과", "power_missing": "② 예측 없음", "thermal_reach10": "③ −10% 가능", "thermal_items": "③ 감시 variant",
             "confidence": "모델 신뢰도"}
    changes = [(label.get(c["item"], c["item"]), c["prev"], c["cur"]) for c in p.get("criteria") or []]
    changes += [(f"기준 · {b['item']}", b["prev"], b["cur"]) for b in p.get("basis") or []]
    changes += [(f"CPU 허용치 · {_short(c['variant_id'])}", _gx(c["prev"]), _gx(c["cur"]))
                for c in p.get("cpu") or []]
    if changes:
        h += ("<h3 style='margin:10px 0 4px'>판정 · 기준 · 정책 변경</h3><table><tr><th>항목</th><th>직전</th><th>현재</th></tr>"
              + "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(a))}</td><td><b>{escape(str(b))}</b></td></tr>" for k, a, b in changes)
              + "</table>")
    else:
        h += "<p class=meta>판정 · 기준 · 정책 변경 없음</p>"
    return h


# ------------------------------------------------------------------- RPT-08
def dumbbell(ctx: dict[str, Any] | None, tol: float | None = None) -> str:
    """Previous project → current per variant (mW + mA@Vbat), tolerance band, reference source badge."""
    rows = [r for r in (ctx or {}).get("rows") or [] if r.get("reference") and r.get("total_mw") is not None]
    if not rows:
        return ""
    bat = (ctx or {}).get("battery") or {}
    k_ma = 1.0 / (float(bat.get("vbat") or 4.0) * float(bat.get("pmic_efficiency") or 0.85))
    rows.sort(key=lambda r: -(r["reference"].get("delta_pct") or 0))
    hi = max(1.0, max(max(r["total_mw"], r["reference"]["reference_mw"]) for r in rows) * 1.08)
    W, L, R, rh = 820, 210, 200, 22
    X = lambda v: L + v / hi * (W - L - R)  # noqa: E731
    col = {"ok": "#2F6F68", "similar": "#B45309", "over": "#9B1C1C"}
    src = {"measurement": "실측", "prediction": "예측", "explicit": "지정값", "synthetic": "합성"}
    svg = [f"<svg width='{W}' height='{len(rows) * rh + 30}' role='img' aria-label='전과제 대비 전력'>"]
    for i, r in enumerate(rows):
        y = 14 + i * rh
        ref, cur = r["reference"]["reference_mw"], r["total_mw"]
        st = r["reference"].get("status")
        if tol:
            svg.append(f"<rect x='{X(ref):.1f}' y='{y - 7}' width='{X(ref * (1 + tol / 100)) - X(ref):.1f}' height='14' fill='#F6EEDC' />")
        svg.append(f"<text x='{L - 8}' y='{y + 4}' font-size='12' text-anchor='end'>{escape(_short(r['variant_id']))}"
                   f" <tspan fill='#7A7468' font-size='10.5'>[{escape(src.get(str(r['reference'].get('source')), str(r['reference'].get('source'))))}]</tspan></text>")
        svg.append(f"<line x1='{X(ref):.1f}' x2='{X(cur):.1f}' y1='{y}' y2='{y}' stroke='{col.get(str(st), '#4A5160')}' stroke-width='2.5' />")
        svg.append(f"<circle cx='{X(ref):.1f}' cy='{y}' r='4.5' fill='#fff' stroke='#4A5160' stroke-width='1.6'><title>전과제 {ref:.0f} mW</title></circle>")
        svg.append(f"<circle cx='{X(cur):.1f}' cy='{y}' r='5' fill='{col.get(str(st), '#4A5160')}'><title>현재 {cur:.0f} mW</title></circle>")
        svg.append(f"<text x='{W - R + 8}' y='{y + 4}' font-size='11.5' class='mono'>{cur:.0f} mW · {r.get('ma') or cur * k_ma:.0f} mA "
                   f"<tspan fill='{col.get(str(st), '#4A5160')}'>{(r['reference'].get('delta_pct') or 0):+.1f}%</tspan></text>")
    svg.append("</svg>")
    return ("<h3 style='margin:4px 0'>전과제 대비 — 기준(○) → 현재(●)</h3>"
            f"<p class=meta>색 = 판정(녹 이하 · 주황 유사 · 빨강 초과) · 띠 = 허용 +{_f(tol, 0) if tol else '—'}% · "
            f"[ ] = 전과제 값 출처 · mA@Vbat = mW ÷ {bat.get('vbat', 4)} V ÷ {bat.get('pmic_efficiency', 0.85)}</p>"
            "<div class=scroll>" + "".join(svg) + "</div>")


def _calibration_top(rows: list[dict[str, Any]]) -> str:
    ranked = sorted(rows, key=lambda r: -abs((r.get("fit") or {}).get("worst_delta_pct") or 0))
    top = ranked[:TOP_N]
    return ("<h3 style='margin:10px 0 4px'>variant별 실측 대조 — 구성 오차 큰 순</h3>" + ar._calibration(top)
            + (_more(f"실측 대조 전체 {len(rows)} variant", ar._calibration(ranked)) if len(rows) > len(top) else ""))


def _options_top(opts: list[dict[str, Any]]) -> str:
    ranked = sorted(opts, key=lambda o: (o.get("best") or {}).get("delta_mw") or 0)
    top = ranked[:TOP_N]
    return (f"<p class=meta>절감 큰 {len(top)}개 variant (전체 {len(opts)})</p>" + ar._power_options(top)
            + (_more(f"Power option 전체 {len(opts)} variant", ar._power_options(ranked)) if len(opts) > len(top) else ""))


def power_top(snap: dict[str, Any]) -> str:
    """Top-N variants by registered power with the CPU / IP / BW split as one stacked bar."""
    rows = [r for r in snap["scenarios"] if r["spec_ok"] and (r.get("power") or {}).get("total_mw") is not None]
    if not rows:
        return ""
    rows.sort(key=lambda r: -r["power"]["total_mw"])
    top = rows[:TOP_N]
    hi = top[0]["power"]["total_mw"] or 1.0
    ref = {(r.get("scenario_id"), r["variant_id"]): (r.get("reference") or {})
           for r in (snap.get("review_context") or {}).get("rows") or []}
    col = (("cpu_mw", ar.C["cpu"], "CPU"), ("hw_mw", ar.C["hw"], "IP"), ("bw_mw", ar.C["bw"], "BW"))
    body = ""
    for r in top:
        p = r["power"]
        bar = "".join(f"<i style='width:{100 * float(p.get(k) or 0) / hi:.1f}%;background:{c}' title='{lbl} {float(p.get(k) or 0):.0f} mW'></i>"
                      for k, c, lbl in col)
        rf = ref.get((r["scenario_id"], r["variant_id"])) or {}
        body += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n><b>{_f(p['total_mw'], 0)}</b></td>"
                 f"<td style='min-width:320px'><div class='bar' style='max-width:none'>{bar}</div></td>"
                 + "".join(f"<td class=n>{_f(p.get(k), 0)}</td>" for k, _, _ in col)
                 + f"<td class=n>{_f(r.get('bw_mbs'), 0)}</td>"
                 f"<td class='n {_REF_CLS.get(str(rf.get('status')), '')}'>{_f(rf.get('delta_pct')) + '%' if rf else '—'}</td></tr>")
    return (f"<h3 style='margin:12px 0 4px'>Power 상위 {len(top)} variant (spec 만족 · 등록 예측)</h3>"
            "<p class=meta><span class=lg><span><i style='background:" + ar.C["cpu"] + "'></i>CPU</span><span><i style='background:" + ar.C["hw"]
            + "'></i>IP</span><span><i style='background:" + ar.C["bw"] + "'></i>BW</span></span></p>"
            "<table><tr><th>Variant</th><th>Total mW</th><th>구성</th><th>CPU</th><th>IP</th><th>BW</th><th>BW MB/s</th><th>전과제 Δ</th></tr>"
            + body + "</table>")


# ------------------------------------------------------------------- CPU-11 section
def cpu_section(cpu: list[dict[str, Any]] | None) -> str:
    if not cpu:
        return ""
    h = ("<p class=meta>CPU what-if에서 “검토서에 포함”한 결과 (서버가 같은 조건으로 SW 증가 sweep을 다시 계산한 요약). "
         "허용치 = min(현재 배치의 가장 큰 OPP 상향 직전 배율, Timing Budget stage SW 여유 소진 배율).</p>"
         "<table><tr><th>Variant</th><th>profile</th><th>topology</th><th>범위</th><th>허용치</th><th>제약</th><th>OPP 계단</th>"
         "<th>현재 mW (시작 → 끝)</th><th>최적 배치 이득</th><th>CPU 기인 BW</th><th>의견</th></tr>")
    for c in cpu:
        s = c.get("summary") or {}
        pts = s.get("points") or []
        p0, pn = (pts[0] if pts else {}), (pts[-1] if pts else {})
        step = s.get("opp_step") or {}
        b0 = s.get("best_at_start") or {}
        tol = s.get("tolerance")
        step_txt = (f"{step.get('cluster')} {_gx(step.get('growth_to'))} {float(step.get('delta_mw') or 0):+.0f} mW" if step else "없음")
        h += (f"<tr><td>{escape(_short(c['variant_id']))}</td>"
              f"<td class=meta>{escape(_short(str(c['profile_ref'])))}{' <b class=warn>합성</b>' if s.get('profile_origin') == 'synthetic' else ''}</td>"
              f"<td class=mono>{escape(str(c['power_params_ref']))}</td>"
              f"<td class=mono>{_gx((s.get('growth_range') or [None])[0])}–{_gx((s.get('growth_range') or [None, None])[1])}</td>"
              f"<td class='n {'fail' if tol is not None and tol < 1.2 else 'ok'}'><b>{_gx(tol) if tol is not None else '범위 밖'}</b></td>"
              f"<td>{'timing 여유' if s.get('binding') == 'timing' else 'OPP 계단' if s.get('binding') == 'opp' else '—'}</td>"
              f"<td class=meta>{escape(step_txt)}</td>"
              f"<td class=n>{_f(p0.get('ref_mw'))} → {_f(pn.get('ref_mw'))}</td>"
              f"<td class=n>{_f(b0.get('delta_mw'))} mW <span class=meta>({len(b0.get('moved') or [])} task)</span></td>"
              f"<td class=n>{_f(p0.get('bw_mw'))} → {_f(pn.get('bw_mw'))} mW</td>"
              f"<td class=meta>{escape(c.get('note') or '')}</td></tr>")
    return h + "</table>"


def rail_bias_block(m: dict[str, Any] | None) -> str:
    rb = (m or {}).get("rail_bias") or []
    if not rb:
        return ""
    lat = (m or {}).get("latency_bias") or {}
    return ("<h3 style='margin:10px 0 4px'>Rail별 체계 오차 (IP는 vdd 단위)</h3><table><tr><th>rail 그룹</th><th>median Δ</th><th>같은 부호</th>"
            "<th>±10%</th><th>실측 median mW</th><th>median |ΔmW|</th><th>판정</th></tr>"
            + "".join(f"<tr><td>{escape(b['label'])}</td><td class='n {_cls(b.get('median'))}'>{_f(b.get('median'))}%</td>"
                      f"<td class=n>{_f(b.get('same_sign_pct'), 0)}%</td><td class=n>{b.get('within10', 0)}/{b.get('n', 0)}</td>"
                      f"<td class=n>{_f(b.get('median_meas_mw'))}</td><td class=n>{_f(b.get('median_abs_delta_mw'))}</td>"
                      f"<td>{escape(str(b.get('label_verdict') or b.get('verdict')))}</td></tr>" for b in rb)
            + (f"<tr><td>Latency (video)</td><td class='n {_cls(lat.get('median'))}'>{_f(lat.get('median'))}%</td><td /><td class=n>"
               f"{lat.get('within10', 0)}/{lat.get('n', 0)}</td><td colspan=2 class=meta>예측 pipeline latency vs 실측 p95</td>"
               f"<td>{escape(str(lat.get('label') or ''))}</td></tr>" if lat.get("n") else "")
            + "</table>")


# ------------------------------------------------------------------- area leads (first line = conclusion)
def _lead_perf(snap: dict[str, Any]) -> str:
    s = snap["spec_summary"]
    low = sorted(({"variant_id": r["variant_id"], "margin_pct": r["sw_margin_pct"]} for r in snap.get("scenarios") or []
                  if r.get("spec_ok") and r.get("sw_margin_pct") is not None and r["sw_margin_pct"] < 10), key=lambda m: m["margin_pct"]) \
        or [m for m in snap.get("sw_margin_top5") or [] if m.get("margin_pct") is not None and m["margin_pct"] < 10]
    t = f"fps 만족 <b>{s['spec_ok']}/{s['explored']}</b>"
    if s["spec_fail"]:
        t += f" · 미달 {s['spec_fail']}건 ({escape(', '.join(_short(f['variant_id']) for f in s['failed'][:3]))})"
    if low:
        t += f" · SW margin 10% 미만 {len(low)}건 (최소 {low[0]['margin_pct']:.0f}% {escape(_short(low[0]['variant_id']))})"
    return _lead(t, "fail" if s["spec_fail"] else "warn" if low else "ok")


def _lead_power(snap: dict[str, Any]) -> str:
    pw = (snap.get("criteria") or {}).get("power") or {}
    rng = snap["spec_summary"].get("power_range_mw")
    t = (f"등록 예측 {_f(rng[0], 0)}–{_f(rng[1], 0)} mW · " if rng else "") + (
        f"전과제 대비 이하 {pw.get('ok', 0)} · 유사 {pw.get('similar', 0)}"
        + (f" · 조건부 {pw.get('conditional', 0)}" if pw.get("basis") == "verdict" else "")
        + f" · <b>초과 {pw.get('over', 0)}</b> · 판정 불가 {len(pw.get('missing') or [])}"
        + (f" · <b>예측 ↔ 실측 반대 {len(pw['flip'])}</b>" if pw.get("flip") else ""))
    return _lead(t, "fail" if pw.get("over") or pw.get("flip") else "warn" if pw.get("missing") or pw.get("conditional") else "ok")


def _lead_lever(snap: dict[str, Any]) -> str:
    th = (snap.get("thermal") or {}).get("items") or []
    reach = sum(1 for i in th if any(p["ask_pct"] == 10 and p["achieved"] for p in i.get("plans") or []))
    opts = snap.get("power_options") or []
    best = min((o["best"]["delta_mw"] for o in opts if o.get("best")), default=None)
    t = (f"발열 −10% 가능 <b>{reach}/{len(th)}</b> (화질 열화 option 포함)" if th else "발열 감시 대상 없음") + (
        f" · 화질 열화 option 최대 {best:+.0f} mW — clock · compression · SW 다음 최후 수단" if best is not None else "")
    return _lead(t, "fail" if th and reach < len(th) else "ok")


def _lead_cpu(snap: dict[str, Any]) -> str:
    cpu = snap.get("cpu") or []
    if not cpu:
        return _lead("CPU what-if 결과 미포함 — CPU what-if 화면에서 “검토서에 포함”", "warn")
    tols = [(c["summary"].get("tolerance"), c["variant_id"]) for c in cpu if (c.get("summary") or {}).get("tolerance") is not None]
    if not tols:
        return _lead(f"CPU what-if {len(cpu)}건 · 범위 안 허용치 제약 없음", "ok")
    t0 = min(tols)
    return _lead(f"CPU what-if {len(cpu)}건 · SW 증가 허용치 최소 <b>{_gx(t0[0])}</b> ({escape(_short(t0[1]))})", "fail" if t0[0] < 1.2 else "ok")


def _lead_model(snap: dict[str, Any]) -> str:
    m = snap.get("model") or {}
    # UX-03: one grade for the whole report (inputs + model); the model-only grade is shown as a component
    conf = ((snap.get("conclusion") or {}).get("confidence") or {}).get("grade") or (m.get("confidence") or {}).get("grade")
    mconf = (m.get("confidence") or {}).get("grade")
    common = [f"{c.upper()} {b['median']:+.0f}%" for c, b in (m.get("bias") or {}).items() if c != "total" and b.get("verdict") == "model_common"]
    rb = [f"{b['label']} {b['median']:+.0f}%" for b in m.get("rail_bias") or [] if b.get("verdict") == "model_common" and b.get("category") == "ip"]
    t = f"신뢰도 <b>{conf or '—'}</b>" + (f" (실측 대조 {mconf} · 입력 반영)" if mconf and mconf != conf else "")
    if common:
        t += f" · 공통 오차 {escape(', '.join(common))}"
    if rb:
        t += f" · IP는 {escape(', '.join(rb))}에 집중"
    if m.get("offsetting"):
        t += f" · total 일치 중 상쇄 {m['offsetting']}건"
    return _lead(t, "fail" if conf == "C" else "warn" if conf == "B" else "ok")


# ------------------------------------------------------------------- RPT-10 dossier
_CAT_NAME = {"fps30": "30 fps", "fps60": "60 fps", "highspeed": "고속", "heavy": "Heavy"}


def _cls_label(c: Any) -> str:
    """Variant class (arch_opinions.classify) as a short tag: 분류 · 해상도 · codec · EIS · heavy kind."""
    if not isinstance(c, dict):
        return str(c or "")
    parts = [_CAT_NAME.get(str(c.get("category")), str(c.get("category") or "")), str(c.get("resolution") or ""),
             str(c.get("codec") or ""), "EIS" if c.get("eis") else "", str(c.get("heavy_kind") or ""),
             f"부하 {c['severity']}" if c.get("severity") else ""]
    return " · ".join(p for p in parts if p and p != "None")

_REF_CLS = {"ok": "ok", "similar": "warn", "over": "fail", "conditional": "warn", "na": "", "uncovered": ""}


def _ref_text(v: dict[str, Any] | None, ref: dict[str, Any]) -> str:
    """REF-05 verdict in one line (falls back to the legacy reference judgement)."""
    from scenario_db.reporting.review_verdict import STATE_LABEL

    if v is None:
        if not ref:
            return "<span class=meta>기준 없음</span>"
        return (f"{_f(ref.get('reference_mw'), 0)} mW → <b class={_REF_CLS.get(str(ref.get('status')), '')}>{_f(ref.get('delta_pct'))}%</b>"
                f" <span class=meta>({escape(str(ref.get('source') or ''))})</span>")
    parts = [f"예측 {v['pred_pct']:+.1f}%" if v.get("pred_pct") is not None else "예측 —"]
    if v.get("meas_pct") is not None:
        parts.append(f"{'실측' if v['basis'] == 'measurement' else '합성 실측'} {v['meas_pct']:+.1f}%")
    cls = "fail" if v.get("flip") else _REF_CLS.get(v["state"], "")
    return (f"{_f(v['ref_mw'], 0)} mW 기준 · <b class={cls}>{('불일치 · ' if v.get('flip') else '') + STATE_LABEL[v['state']]}</b> · "
            + " · ".join(parts) + (f" <span class=meta>({escape(v['why'])})</span>" if v.get("why") else "")
            + f" <span class=meta>[{escape(str(v.get('ref_source') or ''))}]</span>")

def dossier(snap: dict[str, Any]) -> str:
    identities = {(r["scenario_id"], r["variant_id"]) for r in snap["scenarios"]}

    def scoped(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        out = {}
        for row in rows:
            keys = [k for k in identities if k[1] == row["variant_id"]
                    and (not row.get("scenario_id") or k[0] == row["scenario_id"])]
            if len(keys) == 1:  # legacy unscoped rows are usable only when unambiguous
                out[keys[0]] = row
        return out

    ctx = scoped((snap.get("review_context") or {}).get("rows") or [])
    from scenario_db.reporting.review_verdict import VALIDITY_LABEL, fps_validity, power_verdicts

    verd = {(v["scenario_id"], v["variant_id"]): v for v in power_verdicts(snap) if v.get("scenario_id")}
    th = scoped((snap.get("thermal") or {}).get("items") or [])
    opts = scoped(snap.get("power_options") or [])
    cal = scoped(snap.get("calibration") or [])
    cpu = scoped(snap.get("cpu") or [])
    margins = scoped((snap.get("sw_margin_top5") or []) + (snap.get("sw_margin_fail") or []))
    risks: dict[str, list[dict[str, Any]]] = {}
    for r in snap.get("risk_register") or []:
        if r.get("status") in ("closed", "accepted") or r.get("trend") == "resolve_candidate":
            continue
        for v in r.get("affected") or []:
            risks.setdefault(str(v), []).append(r)
    doms: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for d in snap.get("domains") or []:
        doms.setdefault((d["scenario_id"], d["variant_id"]), []).append(d)
    cards = []
    for r in snap["scenarios"]:
        v = r["variant_id"]
        key = (r["scenario_id"], v)
        p = r.get("power") or {}
        ref = (ctx.get(key) or {}).get("reference") or {}
        ma = (ctx.get(key) or {}).get("ma")
        lat = r.get("latency") or {}
        rows: list[tuple[str, str]] = [
            ("판정", f"<b class={'ok' if r['spec_ok'] else 'fail'}>{'fps 만족' if r['spec_ok'] else 'fps 미달'}</b> · {_f(r['fps'], 0)} fps"
             + ("" if r["spec_ok"] or fps_validity(r)[0] == "confirmed" else
                f" <b class=warn>검증 필요 · {VALIDITY_LABEL[fps_validity(r)[0]]}</b> <span class=meta>{escape(fps_validity(r)[1])}</span>")
             + ("" if r.get("prediction_id") or not r["spec_ok"] else " <span class=warn>미등록 (탐색값)</span>")
             + (" · EIS" if r.get("eis_on") else "")
             + ("".join(f"<div class=meta>{escape(e.get('text', ''))}</div>" for e in (r.get("reasons_explained") or [])[:2]) if not r["spec_ok"] else "")),
            ("Power", f"<b>{_f(p.get('total_mw'))} mW</b>{f' · {ma:.0f} mA' if ma else ''} · CPU {_f(p.get('cpu_mw'))} · IP {_f(p.get('hw_mw'))} · BW {_f(p.get('bw_mw'))}"
             f" · {_f(r.get('bw_mbs'), 0)} MB/s"),
            ("전과제", _ref_text(verd.get(key), ref)),
            ("Latency", f"video {_f(lat.get('video_ms'))} ms ({_f(lat.get('video_frames'), 2)} frame) · preview {_f(lat.get('preview_ms'))} ms" if lat else "—"),
        ]
        m = margins.get(key)
        if m:
            mcls = "fail" if m["margin_pct"] < 0 else "warn" if m["margin_pct"] < 10 else "ok"
            rows.append(("SW margin", f"<b class={mcls}>{m['margin_pct']:.1f}%</b>"
                         f" · {escape(str(m.get('stage', '')).upper())} · 병목 {escape(str(m.get('bottleneck') or '—'))}"
                         + (f" · 증가 허용 ×{m['growth_tolerance']:.2f}" if m.get("growth_tolerance") else "")))
        dv = doms.get(key) or []
        if dv:
            tight = min(dv, key=lambda d: d["headroom_pct"] if d["headroom_pct"] is not None else 1e9)
            rows.append(("IP clock", " · ".join(f"{escape(d['domain'])} L{d['level']} {d['speed_mhz']:.0f} MHz" for d in dv[:5])
                         + (f" · 최소 여유 {escape(tight['domain'])} {tight['headroom_pct']:.0f}%" if tight.get("headroom_pct") is not None else "")))
        t = th.get(key)
        if t:
            rows.append(("발열 대응", " · ".join(f"−{q['ask_pct']:.0f}% {'가능' if q['achieved'] else '<b class=fail>미달</b>'} (필요 {q['need_mw']:.0f} / IQ 항목 {q['saving_mw']:.0f} mW)"
                                              for q in t.get("plans") or []) or "평가 없음"))
        o = opts.get(key)
        if o and o.get("best"):
            b = o["best"]
            iq = {"adopted": "IQ 승인", "iq_eval": "IQ 평가 중", "rejected": "IQ 반려", "candidate": "IQ 평가 대기"}
            rows.append(("화질 열화 option", f"{escape(' + '.join(b['labels']))} <b>{b['delta_mw']:+.0f} mW</b> ({_f(b.get('delta_pct'))}%)"
                         + (f" <span class=warn>{iq.get(str(b.get('review_status') or 'candidate'), 'IQ 평가')}</span>"
                            if b.get("iq_eval") == "required" else "") + " <span class=meta>· 최후 수단</span>"))
        c = cal.get(key)
        if c:
            by = {x["category"]: x for x in c["rows"]}
            rows.append(("실측 대조", f"total {_f(c['delta_pct'])}% · " + " · ".join(
                f"{k.upper()} {_f((by.get(k) or {}).get('delta_pct'))}%" for k in ("cpu", "ip", "bw"))
                + (" <b class=warn>상쇄</b>" if c["fit"]["offsetting"] else "") + (" <span class=meta>(합성)</span>" if c.get("synthetic") else "")))
        cs = cpu.get(key)
        if cs:
            s = cs.get("summary") or {}
            rows.append(("CPU", f"SW 증가 허용치 <b>{_gx(s.get('tolerance')) if s.get('tolerance') is not None else '범위 밖'}</b>"
                         f" · {'timing' if s.get('binding') == 'timing' else 'OPP'} 제약 · 최적 재배치 {_f((s.get('best_at_start') or {}).get('delta_mw'))} mW"))
        inp = r.get("inputs") or {}
        if inp.get("sw_timing_source") or inp.get("sensor_support"):
            rows.append(("입력 근거", " · ".join(x for x in (
                f"SW timing {'가정값' if inp.get('sw_timing_source') == 'assumed' else escape(str(inp.get('sw_timing_source')))}"
                + (f" ({escape(str(inp.get('sw_timing_case')))})" if inp.get("sw_timing_case") else "") if inp.get("sw_timing_source") else "",
                f"sensor {escape(str(inp['sensor_support']))}" if inp.get("sensor_support") else "") if x)))
        rk = risks.get(v) or []
        if rk:
            rows.append(("Risk", " ".join(f"{ar._sev(x['severity'])} <span class=mono>{escape(x['label'])}</span> {escape(x['title'])}<br>" for x in rk)))
        sev = "fail" if not r["spec_ok"] or any(x["severity"] == "critical" for x in rk) else "warn" if rk else "ok"
        tag = _cls_label(r.get("cls"))
        cards.append(({"fail": 0, "warn": 1, "ok": 2}[sev], v, f"<article class='dos d-{sev}' id='d-{escape(r['scenario_id'] + '/' + v)}' data-k='{escape((v + ' ' + tag).lower())}'>"
                     f"<h4>{escape(_short(v))} <span class=meta>{escape(r['scenario_id'])} · {escape(tag)}</span></h4><table>"
                     + "".join(f"<tr><th>{k}</th><td>{val}</td></tr>" for k, val in rows) + "</table></article>"))
    cards.sort(key=lambda c: (c[0], c[1]))
    return ("<p class=meta>variant 1장 고정 layout — 같은 항목은 항상 같은 줄. 미달 · risk 있는 variant가 먼저. "
            "검색: variant · 분류 이름 (예: uhd60, 8k, eis)</p>"
            "<input id='dos-q' class='dos-q' placeholder='variant 검색' aria-label='variant 검색' "
            "oninput=\"var q=this.value.toLowerCase();document.querySelectorAll('.dos').forEach(function(e){e.style.display=!q||e.dataset.k.indexOf(q)>=0?'':'none'})\">"
            "<div class='dos-grid'>" + "".join(c[2] for c in cards) + "</div>")


def _coverage_table(cov: dict[str, Any] | None) -> str:
    """COV-02: every scenario of the project, covered or not."""
    if not cov or not cov.get("rows"):
        return ""
    t = cov.get("total") or {}
    rows = sorted(cov["rows"], key=lambda r: (-r["explored"], r["name"]))
    return ("<h3 style='margin:4px 0'>Scenario coverage — 과제 전체</h3><p class=meta>제품 variant = 파생 sub-variant(explored · timing) 제외. "
            "탐색 0인 scenario는 이 보고서의 판정에 포함되지 않음.</p><table><tr><th>Scenario</th><th>제품 variant</th><th>탐색</th><th>등록 예측</th>"
            "<th>실측 (silicon)</th><th>실측 있으나 예측 없음</th><th>전과제 기준</th></tr>"
            + "".join(f"<tr><td>{escape(r['name'])} <span class=meta>{escape(r['scenario_id'])}</span></td><td class=n>{r['variants']}</td>"
                      f"<td class='n {'' if r['explored'] else 'warn'}'>{r['explored']}</td><td class=n>{r['registered']}</td>"
                      f"<td class=n>{r['measured']} ({r['measured_physical']})</td><td class=n>{r['measured_no_prediction']}</td>"
                      f"<td class=n>{r['reference']}</td></tr>" for r in rows)
            + f"<tr><th>합계</th><th class=n>{t.get('variants', 0)}</th><th class=n>{t.get('explored', 0)}</th><th class=n>{t.get('registered', 0)}</th>"
              f"<th class=n>{t.get('measured', 0)} ({t.get('measured_physical', 0)})</th><th class=n>{t.get('measured_no_prediction', 0)}</th>"
              f"<th class=n>{t.get('reference', 0)}</th></tr></table>")


TIER_CSS = """
.lead{font-size:15.5px;margin:0 0 10px;padding:6px 10px;border-left:4px solid #9A9387;background:#FBFAF7}
.lead.ok{border-color:#2F6F68}.lead.warn{border-color:#B45309}.lead.fail{border-color:#9B1C1C}
nav .tier{font-size:11.5px;color:#7A7468;font-weight:700;margin-left:6px}
.dos-q{font:inherit;padding:6px 10px;border:1px solid #E4DED3;border-radius:6px;width:280px;margin:4px 0 10px}
.dos-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:12px}
.dos{border:1px solid #E4DED3;border-left:5px solid #2F6F68;border-radius:8px;padding:8px 12px;break-inside:avoid}
.dos.d-warn{border-left-color:#B45309}.dos.d-fail{border-left-color:#9B1C1C}.dos h4{margin:2px 0 6px;font-size:15px}
.dos th{width:92px;background:none;font-weight:600}.dos td,.dos th{padding:3px 6px;font-size:13px}
section.tier1{border-top:4px solid #23262E}
details.more{margin:6px 0 10px}details.more>summary{cursor:pointer;color:#2F6F68;font-size:13.5px}
@media print{details.more:not([open]){display:none}.dos-q{display:none}.dos-grid{grid-template-columns:1fr 1fr}section.tier1-end{break-after:page}section.tier3{break-before:page}}
"""


def tiered_sections(snap: dict[str, Any]) -> list[tuple[str, str, str | None, int]]:
    """(title, body, omitted_reason, tier)."""
    s = snap["spec_summary"]
    ok_rows = {(r["scenario_id"], r["variant_id"]) for r in snap["scenarios"] if r["spec_ok"]}
    th = snap.get("thermal") or {}
    from scenario_db.reporting.review_summary import decomp_table, dq_table, drivers_table, glossary, ladder_table, sw_table, tier0, verdict_table

    out: list[tuple[str, str, str | None, int]] = []
    if (snap.get("scope") or {}).get("kind") == "project":
        out.append(("경영 요약", tier0(snap), None, 0))
    out.append(("결론", ar._tier1(snap), None, 1))
    if "risk_register" in snap:
        out.append(("Risk register", drivers_table(snap) + ar._risk_register(snap["risk_register"], snap.get("scope") or {}), None, 1))
    out.append(("이전 보고서 대비", previous_block(snap.get("previous")),
                None if snap.get("previous") else "같은 과제의 이전 과제 보고서 없음 (첫 보고서)", 1))
    lat_rows = [r for r in snap["scenarios"] if r.get("latency")]
    lat_top = sorted(lat_rows, key=lambda r: (r["spec_ok"], -((r.get("latency") or {}).get("video_frames") or 0)))[:TOP_N]
    doms = snap.get("domains") or []
    dom_head = {}
    for d in doms:
        if d.get("headroom_pct") is not None:
            key = (d["scenario_id"], d["variant_id"])
            dom_head[key] = min(dom_head.get(key, 1e9), d["headroom_pct"])
    tight = set(sorted(dom_head, key=lambda v: dom_head[v])[:TOP_N])
    perf = (_lead_perf(snap) + ar._spec(s)
            + f"<h3 style='margin:12px 0 4px'>Latency · 출력 간격 — 미달 · frame 지연 큰 {len(lat_top)}개</h3>" + ar._latency(lat_top)
            + (_more(f"Latency 전체 {len(lat_rows)}개", ar._latency(lat_rows)) if len(lat_rows) > len(lat_top) else "")
            + sw_table(snap)
            + "<h3 style='margin:12px 0 4px'>SW margin</h3>" + (ar._margins(snap["sw_margin_top5"]) if snap["sw_margin_top5"] else "<p class=meta>SW margin 계산 결과 없음</p>")
            + ar._fail_margins(snap.get("sw_margin_fail") or [])
            + f"<h3 style='margin:12px 0 4px'>IP 필요 clock — DVFS 여유 작은 순 (상위 {TOP_N} · spec 만족)</h3>"
            + ar._domains([d for d in doms if (d["scenario_id"], d["variant_id"]) in tight])
            + (_more(f"IP clock 전체 {len(dom_head)} variant", ar._domains(doms)) if len(dom_head) > len(tight) else "")
            + "<details><summary>IP별 상세 (필요 → 설정 MHz)</summary>"
            + ar._clocks([c for c in snap["clocks"] if (c["scenario_id"], c["variant_id"]) in ok_rows]) + "</details>")
    power = (_lead_power(snap) + dumbbell(snap.get("review_context"), ((snap.get("criteria") or {}).get("power") or {}).get("tolerance_pct"))
             + (verdict_table(snap) or ar._review(snap.get("review_context"))) + decomp_table(snap)
             + power_top(snap)
             + _more(f"Power · BW 분포 (조합 × SW 통계) 전체", ar._boxes(snap["scenarios"]))
             + _more("CPU / IP / BW 구성 전체", ar._split(snap["scenarios"]))
             + (_more(f"Compression 절감 — buffer {len(snap['compression'])}개 (IP 지원 확인 · 잠재 구분)",
                      ar._compression(snap["compression"], snap["scenarios"])) if snap["compression"]
                else "<p class=meta>BW를 줄이는 compression buffer가 없음</p>"))
    lever = (_lead_lever(snap) + "<h3 style='margin:4px 0'>발열 대응 (−10 / −20%)</h3>"
             + (ar._thermal(th) if th.get("items") else f"<p class=meta>{escape(th.get('reason') or 'review_policy에 thermal_watch 대상이 없음')}</p>")
             + ladder_table(snap)
             + "<h3 style='margin:12px 0 4px'>화질 열화 option — 최후 수단 (IQ 평가 대상)</h3>"
             + (_options_top(snap.get("power_options") or []) if snap.get("power_options")
                else "<p class=meta>power option 결과 없음 — 조합 탐색에서 power option을 켜고 실행</p>"))
    model = (_lead_model(snap) + ar._model_block(snap.get("model")) + rail_bias_block(snap.get("model"))
             + _calibration_top(snap.get("calibration") or []) + ar.clock_block(snap.get("clock_residency") or []))
    out += [
        ("성능 · Timing", perf, None, 2),
        ("Power 구성", power, None, 2),
        ("Lever · 발열", lever, None, 2),
        ("CPU · SW", _lead_cpu(snap) + cpu_section(snap.get("cpu")), None, 2),
        ("예측 ↔ 실측", model, None, 2),
        ("분류별 검토 의견", ar._opinions(snap.get("opinions") or []), None, 2),
        ("검토 범위 · 모델", _coverage_table(snap.get("coverage")) + dq_table(snap) + ar._overview(snap["overview"]) + ar._scope(snap.get("scope"))
         + glossary(),
         None, 2),
        ("Scenario dossier", dossier(snap), None, 3),
        ("Scenario 요약 표", ar._scenarios(snap["scenarios"]), None, 3),
        ("변경 이력", ar._history(snap["history"]), None if snap["history"] else "이전 등록 예측 대비 변경 없음", 3),
        ("부록", ar._appendix(snap["appendix"]), None, 3),
    ]
    return out
