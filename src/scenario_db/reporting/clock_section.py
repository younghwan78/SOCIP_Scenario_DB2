"""Report block: measured clock-domain residency (CPU cluster · DSU · GPU), inside ④ 실측 대조.

Rows come from ``api.services.clock_residency`` (same notes as the calibration page), frozen in
the snapshot under ``clock_residency``.
"""
from __future__ import annotations

from html import escape
from typing import Any

# sequential single hue: low frequency = light, high = dark (OPP order, not a category)
_LO, _HI = (0xD7, 0xEC, 0xE7), (0x17, 0x4D, 0x47)


def opp_color(i: int, n: int) -> str:
    t = 0.0 if n <= 1 else i / (n - 1)
    return "#" + "".join(f"{round(a + (b - a) * t):02X}" for a, b in zip(_LO, _HI))


def freq_color(mhz: float, fmax: float | None, i: int, n: int) -> str:
    """By the fraction of fmax when known (same colour = same headroom across domains), else by rank."""
    if fmax and fmax > 0:
        return opp_color(round(max(0.0, min(1.0, mhz / fmax)) * 20), 21)
    return opp_color(i, n)


def _mhz(v: Any) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v / 1000:.2f} GHz" if v >= 1000 else f"{v:.0f} MHz"


def _pct(v: Any) -> str:
    return "—" if not isinstance(v, (int, float)) else f"{v * 100:.0f}%"


def residency_bar(bins: list[dict[str, Any]], *, width: int = 260, height: int = 12, fmax: float | None = None) -> str:
    """Inline SVG stacked bar, one segment per frequency (ascending), colour = fraction of fmax, title = MHz · share."""
    x, parts = 0.0, []
    n = len(bins)
    for i, b in enumerate(bins):
        w = width * float(b["ratio"])
        parts.append(f"<rect x='{x:.1f}' y='0' width='{max(w, 0.0):.1f}' height='{height}' fill='{freq_color(float(b['mhz']), fmax, i, n)}'>"
                     f"<title>{escape(_mhz(b['mhz']))} · {float(b['ratio']) * 100:.1f}%</title></rect>")
        x += w
    return (f"<svg width='{width}' height='{height}' role='img' aria-label='clock residency'>"
            f"<rect width='{width}' height='{height}' fill='#EFEAE1'/>{''.join(parts)}</svg>")


def clock_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    h = ["<h3 style='margin-top:18px'>Clock 분포 실측 (CPU · DSU · GPU)</h3>",
         "<p class='meta'>측정 중 각 clock domain이 어떤 주파수에 얼마나 머물렀는지. 막대 = 주파수 순 시간 비율, 색 = fmax 대비 "
         "주파수(연한 색 낮음 → 진한 색 fmax 근처), <b>running</b> 기준은 idle을 뺀 동작 시간 기준(dynamic power 계산에 사용)입니다. "
         "고 OPP = fmax의 80% 이상. 메모는 Calibration 화면과 같은 규칙으로 생성됩니다.</p>"]
    for r in rows:
        tag = " <b class=warn>합성</b>" if r.get("synthetic") else ""
        h.append(f"<div class='op'><h3>{escape(str(r['variant_id']).replace('cam-rec-', ''))}{tag} "
                 f"<span class='meta' style='font-weight:400'>{escape(str(r.get('measured_at') or '')[:10])} · "
                 f"{escape(str(r.get('measurement_id') or ''))}</span></h3>")
        if r.get("summary"):
            h.append("<ul>" + "".join(f"<li>{escape(s)}</li>" for s in r["summary"]) + "</ul>")
        h.append("<div class='scroll'><table><tr><th>Domain</th><th>기준</th><th>분포 (낮음 → 높음)</th><th>평균</th>"
                 "<th>최빈</th><th>고 OPP</th><th>동작</th><th>pass JSD</th><th>메모</th></tr>")
        for d in r["domains"]:
            notes = "".join(f"<div class='{'warn' if n['level'] == 'warn' else 'meta'}'>{escape(n['text'])}</div>" for n in d.get("notes") or [])
            jsd = d.get("pass_jsd")
            h.append(
                f"<tr><td><b>{escape(d['domain'])}</b> <span class='meta'>{escape(d['class_label'])}</span></td>"
                f"<td>{'running' if d['basis'] == 'active' else '전체'}</td>"
                f"<td>{residency_bar(d['bins'], fmax=d.get('opp_max_mhz'))}<div class='meta' style='font-size:12px'>{escape(_mhz(d['bins'][0]['mhz']))} … "
                f"{escape(_mhz(d['bins'][-1]['mhz']))}{' / fmax ' + escape(_mhz(d['opp_max_mhz'])) if d.get('opp_max_mhz') else ''}</div></td>"
                f"<td class=n>{escape(_mhz(d['mean_mhz']))}</td>"
                f"<td class=n>{escape(_mhz(d['dominant_mhz']))} ({_pct(d['dominant_share'])})</td>"
                f"<td class='n {'warn' if (d['high_share'] or 0) >= 0.3 else ''}'>{_pct(d['high_share'])}</td>"
                f"<td class=n>{_pct(d.get('active_ratio'))}</td>"
                f"<td class='n {'warn' if isinstance(jsd, (int, float)) and jsd > 0.05 else ''}'>{'—' if jsd is None else f'{jsd:.3f}'}</td>"
                f"<td style='max-width:420px'>{notes or '<span class=meta>—</span>'}</td></tr>")
        h.append("</table></div></div>")
    return "".join(h)


def report_rows(variant_id: str, scenario_id: str, measurement: Any, view: dict[str, Any]) -> dict[str, Any]:
    """Snapshot row (compact, frozen) for one measured variant."""
    from scenario_db.api.services.calibration import data_origin, is_synthetic

    domains = []
    for d in view["domains"]:
        s = d["active"] or d["wall"]
        domains.append({"domain_class": d["domain_class"], "class_label": d["class_label"], "domain": d["domain"],
                        "is_dsu": d["is_dsu"], "basis": "active" if d["active"] else "wall", "bins": s["bins"],
                        "mean_mhz": s["mean_mhz"], "dominant_mhz": s["dominant_mhz"], "dominant_share": s["dominant_share"],
                        "high_share": s["high_share"], "opp_max_mhz": d["opp_max_mhz"], "active_ratio": d["active_ratio"],
                        "pass_jsd": d["pass_jsd"], "notes": d["notes"]})
    return {"scenario_id": scenario_id, "variant_id": variant_id, "measurement_id": measurement.id,
            "measured_at": measurement.measured_at.isoformat() if measurement.measured_at else None,
            "synthetic": is_synthetic(measurement.provenance), "origin": data_origin(measurement.provenance),
            "summary": view["summary"], "rules_version": view["rules_version"], "domains": domains}


def clock_sheet(snap: dict[str, Any]) -> tuple[str, list[str], list[list[Any]]]:
    rows = []
    for r in snap.get("clock_residency") or []:
        for d in r["domains"]:
            rows.append([r["variant_id"], r["synthetic"], str(r.get("measured_at") or "")[:10], d["class_label"], d["domain"],
                         d["basis"], d["mean_mhz"], d["dominant_mhz"], round(d["dominant_share"], 4), d["high_share"],
                         d.get("active_ratio"), d.get("pass_jsd"), d.get("opp_max_mhz"),
                         " | ".join(f"{b['mhz']:g}:{b['ratio']:.4f}" for b in d["bins"]),
                         " / ".join(n["text"] for n in d.get("notes") or [])])
    return ("Clock 분포", ["variant", "합성", "측정일", "class", "domain", "기준", "평균 MHz", "최빈 MHz", "최빈 비율", "고 OPP 비율",
                         "동작 비율", "pass JSD", "fmax MHz", "분포 (MHz:비율)", "메모"], rows)
