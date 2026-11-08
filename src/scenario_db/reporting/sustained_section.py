"""Sustained AP + mem current section (``snapshot["sustained"]``, review_policy.sustained_current)."""

from __future__ import annotations

from html import escape
from typing import Any

_STATUS = {"over": ("초과 — 절감 검토", "fail"), "watch": ("주의", "warn"), "ok": ("이내", "ok")}


def _short(v: str) -> str:
    return v.replace("cam-rec-", "")


def _plan(r: dict[str, Any]) -> str:
    p, ap = r.get("plan"), r.get("approved_plan")
    if r["status"] != "over":
        return "<td class=meta>—</td>"
    if not p and r.get("watched"):
        best = r.get("watch_best_mw")
        if best is None:
            return "<td class=meta>발열 감시 항목 — 아래 −10 / −20% 표 참조</td>"
        cls = "warn" if best >= r["need_mw"] else "fail"
        return (f"<td class='{cls}'>발열 감시 계획 최대 −{best:.0f} mW ({'한도 도달 가능' if best >= r['need_mw'] else '한도까지 부족'})"
                "<div class=meta>−10 / −20% 계획 기준 (아래 표) · 화질 유지 최적 기준</div></td>")
    if not p:
        return "<td class=meta>절감 조합 미계산 (조합 탐색 결과 없음)</td>"
    if p.get("picked") == ["switch:iq_keep"]:
        return (f"<td class=ok>화질 유지 최적 조합으로 등록 변경 시 한도 이내<div class=meta>{p['saving_mw']:.0f} mW · 추가 절감 불필요</div></td>")
    sure = f"확정 {ap['saving_mw']:.0f} mW" if ap else "확정 —"
    verdict = ("확정 항목으로 한도 도달" if ap and ap.get("achieved") else
               "IQ 평가 항목 포함 시 도달" if p.get("achieved") else "부족 — 성능 조건 협의")
    cls = "ok" if ap and ap.get("achieved") else "warn" if p.get("achieved") else "fail"
    return (f"<td class='{cls}'>{escape(verdict)}<div class=meta>{escape(sure)} · 최대 {p['saving_mw']:.0f} mW"
            + (f" · {escape(', '.join((p.get('picked') or [])[:3]))}" if p.get("picked") else "") + "</div></td>")


def sustained_block(snap: dict[str, Any], top: int = 15) -> str:
    sv = snap.get("sustained")
    if not sv:
        return ("<h3 style='margin:4px 0'>지속 전류 (AP + mem)</h3><p class=meta>review_policy.sustained_current 미설정 — "
                "지속 AP + mem 전류 한도(예: limit_ma: 1200)를 설정하면 전 scenario를 한도 대비로 판정합니다.</p>")
    rows = sv["rows"]
    limit, watch = sv["limit_ma"], sv["watch_ma"]
    scale = max([limit * 1.25] + [r["ma"] for r in rows]) or 1.0
    over = [r for r in rows if r["status"] == "over"]

    def table(rs: list[dict[str, Any]]) -> str:
        h = ("<table><tr><th>#</th><th>Variant</th><th>Total mW</th><th>AP + mem mA</th><th style='min-width:240px'>한도 대비</th>"
             "<th>판정</th><th>필요 절감</th><th>절감 조합 (기준: 화질 유지 최적)</th></tr>")
        for i, r in enumerate(rs, 1):
            lbl, cls = _STATUS[r["status"]]
            w = 100 * r["ma"] / scale
            bar = (f"<div style='position:relative;height:12px;background:#EFEAE1;border-radius:3px'>"
                   f"<i style='position:absolute;left:0;top:0;bottom:0;width:{w:.1f}%;background:"
                   f"{'#9B1C1C' if r['status'] == 'over' else '#B45309' if r['status'] == 'watch' else '#2F6F68'};border-radius:3px'></i>"
                   f"<i style='position:absolute;left:{100 * limit / scale:.1f}%;top:-3px;bottom:-3px;width:2px;background:#23262E' "
                   f"title='한도 {limit:.0f} mA'></i>"
                   f"<i style='position:absolute;left:{100 * watch / scale:.1f}%;top:0;bottom:0;width:1px;background:#7A7468' "
                   f"title='주의 {watch:.0f} mA'></i></div>")
            need = f"−{r['need_mw']:.0f} mW<div class=meta>−{r['need_ma']:.0f} mA</div>" if r["need_mw"] > 0 else "—"
            h += (f"<tr><td class=n>{i}</td><td>{escape(_short(r['variant_id']))}</td><td class=n>{r['total_mw']:,.0f}</td>"
                  f"<td class=n><b>{r['ma']:,.0f}</b></td><td>{bar}</td><td class='{cls}'>{lbl}</td><td class=n>{need}</td>{_plan(r)}</tr>")
        return h + "</table>"

    base = f" + AP 공통 {sv['base_mw']:.0f} mW" if sv.get("base_mw") else ""
    out = ("<h3 style='margin:4px 0'>지속 전류 (AP + mem) — 발열 기준</h3>"
           f"<p class=meta>한도 <b>{limit:.0f} mA</b> (≈ {sv['limit_mw']:,.0f} mW) · 주의 ≥ {watch:.0f} mA (×{sv['watch_ratio']:.2f}). "
           f"AP + mem = 등록 예측 total(CPU + IP + 가정 부하 + BW(MIF · DRAM)){base}, "
           f"mA = mW ÷ {sv.get('vbat')} V ÷ {sv.get('pmic_efficiency')}. 온도는 phone 방열 성능에 따라 달라 지속 전류로 판정. "
           "초과 scenario의 절감 조합은 화질 유지 최적 조합에서 clock → IQ 승인 option → lossy → IQ 평가 option 순으로 한도까지."
           + (f" {escape(str(sv['note']))}" if sv.get("note") else "") + "</p>")
    if not rows:
        return out + "<p class=meta>등록 예측 없음</p>"
    shown = rows[:max(top, len(over))]
    out += table(shown)
    if len(rows) > len(shown):
        out += f"<details class='more'><summary>전체 {len(rows)} variant ▸</summary>{table(rows)}</details>"
    return out


def sustained_lead(snap: dict[str, Any]) -> str | None:
    sv = snap.get("sustained")
    if not sv:
        return None
    over = sum(1 for r in sv["rows"] if r["status"] == "over")
    watch = sum(1 for r in sv["rows"] if r["status"] == "watch")
    top = sv["rows"][0] if sv["rows"] else None
    return (f"지속 전류 {sv['limit_ma']:.0f} mA 초과 <b>{over}</b> · 주의 {watch} / {len(sv['rows'])}"
            + (f" · 최대 {escape(_short(top['variant_id']))} {top['ma']:,.0f} mA" if top else ""))
