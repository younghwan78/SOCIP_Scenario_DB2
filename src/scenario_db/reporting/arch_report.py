"""Architecture review report: frozen snapshot from an exploration run + HTML render."""

from __future__ import annotations

import hashlib
import re
from html import escape
from typing import Any

from scenario_db.reporting.arch_opinions import build_opinions, classify

_CLOCK_RE = re.compile(r"^(\w+): required_clock ([\d.]+)MHz exceeds max DVFS speed ([\d.]+)MHz$")


def compact_reasons(reasons: list[str]) -> list[str]:
    """'byrp: required 1076MHz exceeds ...' x N -> one line listing the IPs."""
    grouped: dict[tuple[str, str], list[str]] = {}
    out: list[str] = []
    for r in reasons:
        m = _CLOCK_RE.match(r)
        if m:
            grouped.setdefault((m.group(2), m.group(3)), []).append(m.group(1))
        elif r not in out:
            out.append(r)
    for (req, mx), nodes in grouped.items():
        out.append(f"{', '.join(nodes)}: 필요 clock {float(req):.0f} MHz > DVFS max {float(mx):.0f} MHz")
    return out

MODEL_LIMITS = [
    "MIF DVFS는 BW 전력에 반영되지 않음 (BW 전력 = MB/s × coeff).",
    "CPU 전력은 단일 cluster/주파수/전압 가정 (Linux EM 계수 × busy time).",
    "Compression은 BW만 감소 (encoder/decoder 전력, 화질 영향 미반영). catalog에 없는 ratio는 assumed.",
    "DVFS headroom은 domain 단위 level 상향 (V² scaling), 필요 clock보다 빠른 level만 탐색.",
    "120 fps 이상 NRT batch 처리 미모델.",
]


def build_snapshot(
    run: dict[str, Any],
    predictions: dict[tuple[str, str], dict[str, Any]],
    changes: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """run: exploration run row as dict; predictions: variant -> current prediction row dict;
    changes: variant -> attribution vs the superseded prediction.
    Classification uses the run's frozen conditions, never the mutable catalog."""
    variants = [v for v in run["variants"] if v.get("variant_id")]
    ok = [v for v in variants if v["spec_ok"]]
    sample_dvfs = bool(run.get("dvfs_table_ref") and "sample" in str(run["dvfs_table_ref"]))
    rows = []
    for v in variants:
        pred = predictions.get((v["scenario_id"], v["variant_id"]))
        chosen = (pred or {}).get("metrics") or {}
        rec = v.get("recommended") or {}
        worst = (v.get("sw_margin") or {}).get("worst") or {}
        rows.append({
            "cls": classify(v["variant_id"], v["scenario_id"], v["fps"], v["eis_on"], v.get("design_conditions"), v.get("severity")),
            "sw_margin_pct": worst.get("margin_pct"), "sw_stage": worst.get("stage"), "sw_bottleneck": worst.get("bottleneck"),
            "variant_id": v["variant_id"], "scenario_id": v["scenario_id"], "fps": v["fps"],
            "spec_ok": v["spec_ok"], "reasons": compact_reasons(v["spec_reasons"]), "eis_on": v["eis_on"],
            "prediction_id": (pred or {}).get("id"), "selection_rule": (pred or {}).get("selection_rule"),
            "power": chosen.get("power") or {k: rec.get(k) for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_ip_mw", "bw_cpu_mw")},
            "bw_mbs": chosen.get("bw_mbs", rec.get("bw_mbs")),
            "baseline_bw_mbs": (v.get("baseline") or {}).get("bw_mbs"),
            "baseline_total_mw": (v.get("baseline") or {}).get("total_mw"),
            "compression": chosen.get("compression", rec.get("compression", [])),
            "dvfs": chosen.get("dvfs", rec.get("dvfs", {})),
            "distribution": v["distribution"], "verified": chosen.get("verified") if pred else rec.get("verified"),
            "lossy": (chosen.get("lossy", any(b.get("lossy") for b in v.get("buffers", [])
                        if b["buffer"] in chosen.get("compression", []))) if pred else rec.get("lossy")),
            "assumed_ratio": (chosen.get("assumed_ratio", any(b.get("ratio_source") == "assumed"
                                for b in v.get("buffers", []) if b["buffer"] in chosen.get("compression", [])))
                              if pred else rec.get("assumed_ratio")),
        })

    clocks = []
    for v in variants:
        pred = predictions.get((v["scenario_id"], v["variant_id"]))
        ips = ((pred or {}).get("metrics") or {}).get("ips") or (v.get("objective_slice") or {}).get("ips") or []
        req = {ip["node"]: ip.get("required_clock_mhz") for ip in (v.get("objective_slice") or {}).get("ips") or []}
        for ip in ips:
            clocks.append({
                "scenario_id": v["scenario_id"], "variant_id": v["variant_id"], "node": ip["node"], "stage": ip["stage"],
                "dvfs_group": ip["dvfs_group"], "required_mhz": req.get(ip["node"]),
                "set_mhz": ip["set_clock_mhz"], "level": ip["dvfs_level"], "voltage_mv": ip["voltage_mv"],
                "headroom_pct": round(100 * (ip["set_clock_mhz"] / req[ip["node"]] - 1), 1)
                if req.get(ip["node"]) else None,
            })

    domains = []
    for v in variants:
        levels = ((predictions.get((v["scenario_id"], v["variant_id"])) or {}).get("metrics") or {}).get("dvfs") \
            or (v.get("recommended") or {}).get("dvfs") or {}
        for d in (v.get("objective_slice") or {}).get("domains") or v.get("domains") or []:
            lvl = levels.get(d["domain"], d["base_level"])
            opt = next((o for o in d["options"] if o["level"] == lvl), d["options"][0])
            driver = max((c for c in clocks if c["scenario_id"] == v["scenario_id"] and c["variant_id"] == v["variant_id"] and c["dvfs_group"] == d["domain"]
                          and c["required_mhz"]), key=lambda c: c["required_mhz"], default=None)
            domains.append({"scenario_id": v["scenario_id"], "variant_id": v["variant_id"], "spec_ok": v["spec_ok"], "domain": d["domain"],
                            "level": lvl, "speed_mhz": opt["speed_mhz"], "voltage_mv": opt["voltage_mv"],
                            "required_mhz": d["max_required_mhz"], "driver": driver["node"] if driver else None,
                            "headroom_pct": round(100 * (opt["speed_mhz"] / d["max_required_mhz"] - 1), 1)
                            if d["max_required_mhz"] else None})

    comp: dict[tuple[str, str], dict[str, Any]] = {}
    for v in variants:
        pred = predictions.get((v["scenario_id"], v["variant_id"]))
        chosen = set(pred["metrics"].get("compression", []) if pred else (v.get("recommended") or {}).get("compression", []))
        for b in v.get("buffers") or []:
            if "delta_mbs" not in b:
                continue
            c = comp.setdefault((v["scenario_id"], b["buffer"]), {
                "scenario_id": v["scenario_id"], "buffer": b["buffer"], "mode": b.get("mode"), "ratio": b.get("comp_ratio"),
                "ratio_source": b.get("ratio_source"), "support": b.get("support"), "lossy": b.get("lossy"),
                "variants": 0, "selected": 0, "delta_mbs": 0.0, "delta_mw": 0.0,
                "selected_delta_mbs": 0.0, "selected_delta_mw": 0.0,
            })
            c["variants"] += 1
            c["delta_mbs"] += b["delta_mbs"]
            c["delta_mw"] += b["delta_mw"]
            if b["buffer"] in chosen:
                c["selected"] += 1
                c["selected_delta_mbs"] += b["delta_mbs"]
                c["selected_delta_mw"] += b["delta_mw"]
    comp_rows = sorted((c for c in comp.values() if c["delta_mbs"] < -0.5), key=lambda c: c["delta_mbs"])
    for c in comp_rows:
        for k in ("delta_mbs", "delta_mw", "selected_delta_mbs", "selected_delta_mw"):
            c[k] = round(c[k], 2)

    margins = []
    for v in variants:
        m = v.get("sw_margin") or {}
        w = m.get("worst")
        if not w:
            continue
        margins.append({"variant_id": v["variant_id"], "fps": v["fps"], "verdict": m.get("verdict"), "spec_ok": v["spec_ok"],
                        **w, "growth_tolerance": m.get("growth_tolerance"),
                        "recommendations": m.get("recommendations", [])})
    margins.sort(key=lambda r: (r["margin_pct"], -r["sw_share_pct"]))

    history = []
    for (sid, vid), ch in changes.items():
        history.append({"scenario_id": sid, "variant_id": vid, "delta_mw": ch["delta_mw"], "delta_pct": ch["delta_pct"],
                        "by_category": ch["by_category"], "top": ch["factors"][:4],
                        "context": [_ctx(c) for c in ch["context_changes"] if c["item"] != "exploration_run_ref"]})

    totals = [r["power"]["total_mw"] for r in rows if r["spec_ok"] and r["power"].get("total_mw") is not None]
    return {
        "overview": {
            "run_id": run["id"], "run_title": run["title"], "run_created_at": str(run.get("created_at") or ""),
            "target_soc": run.get("soc_ref"), "project": run.get("project_ref"),
            "scenario_type": run["scenario_type"], "dvfs_table_ref": run.get("dvfs_table_ref"),
            "sample_dvfs": sample_dvfs, "objective": run["spec"].get("objective"),
            "axes": run["spec"].get("axes"), "constraints": run["spec"].get("constraints"),
            "engine_rev": run.get("engine_rev"), "model_limits": MODEL_LIMITS,
        },
        "spec_summary": {
            "explored": len(variants), "spec_ok": len(ok), "spec_fail": len(variants) - len(ok),
            "failed": [{"variant_id": v["variant_id"], "reasons": compact_reasons(v["spec_reasons"])[:3]}
                       for v in variants if not v["spec_ok"]],
            "errors": run.get("errors") or [],
            "power_range_mw": [round(min(totals), 1), round(max(totals), 1)] if totals else None,
        },
        "opinions": build_opinions(rows, domains),
        "scenarios": rows,
        "clocks": clocks,
        "compression": comp_rows,
        "sw_margin_top5": [m for m in margins if m["spec_ok"]][:5],
        "sw_margin_fail": [m for m in margins if not m["spec_ok"]],
        "domains": domains,
        "history": history,
        "appendix": {
            "counts": run.get("summary"),
            "prediction_ids": sorted(p["id"] for p in predictions.values()),
            "warnings": sorted({w for v in variants for w in (v.get("warnings") or [])})[:40],
        },
    }


def _ctx(c: dict[str, Any]) -> dict[str, Any]:
    if c["item"] == "compression buffers":
        return {"item": "compression", "old": f"−{len(c['old'])} buf", "new": f"+{len(c['new'])} buf",
                "detail": {"off": c["old"], "on": c["new"]}}
    return c


# ------------------------------------------------------------------- HTML
C = {"cpu": "#0072B2", "bwcpu": "#56B4E9", "hw": "#009E73", "bw": "#E69F00", "total": "#4A5160", "ink": "#23262E", "mute": "#7A7468",
     "line": "#E4DED3", "ok": "#2F6F68", "fail": "#9B1C1C"}


def render_html(title: str, snap: dict[str, Any]) -> str:
    o, s = snap["overview"], snap["spec_summary"]
    parts = [
        "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>",
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>",
        f"<header><h1>{escape(title)}</h1><div class='meta'>{escape(str(o['target_soc']))} · "
        f"{escape(o['scenario_type'])} · {escape(o['run_id'])} · DVFS {escape(str(o['dvfs_table_ref']))}"
        f"{' <b class=warn>SAMPLE</b>' if o['sample_dvfs'] else ''}</div></header>",
        "<nav>" + "".join(f"<a href='#s{i}'>{t}</a>" for i, t in enumerate(SECTIONS, 1)) + "</nav><main>",
        _sec(1, _overview(o)),
        _sec(2, _spec(s)),
        _sec(3, _opinions(snap.get("opinions") or [])),
        _sec(4, _scenarios(snap["scenarios"])),
        _sec(5, _domains(snap.get("domains") or []) + "<details><summary>IP별 상세 (필요 → 설정 MHz)</summary>"
             + _clocks([c for c in snap["clocks"] if (c["scenario_id"], c["variant_id"]) in
                        {(r["scenario_id"], r["variant_id"]) for r in snap["scenarios"] if r["spec_ok"]}])
             + "</details>"),
        _sec(6, _boxes(snap["scenarios"])),
        _sec(7, _split(snap["scenarios"])),
        _sec(8, _compression(snap["compression"], snap["scenarios"])),
        _sec(9, _margins(snap["sw_margin_top5"]) + _fail_margins(snap.get("sw_margin_fail") or [])),
        _sec(10, _history(snap["history"])),
        _sec(11, _appendix(snap["appendix"])),
        "</main></body></html>",
    ]
    return "".join(parts)


def html_sha256(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


SECTIONS = ["개요", "Spec 만족", "분류별 검토 의견", "Scenario 요약", "IP 필요 clock", "Power·BW 분포", "CPU/IP/BW",
            "Compression 절감", "SW margin Top5", "변경 이력", "부록"]

_CSS = """
body{font:13px/1.45 -apple-system,'Segoe UI','Malgun Gothic',sans-serif;color:#23262E;background:#FBFAF7;margin:0}
header{padding:18px 28px;border-bottom:1px solid #E4DED3;background:#fff}h1{margin:0;font-size:20px}
.meta{color:#7A7468;margin-top:4px}nav{position:sticky;top:0;background:#FBFAF7;padding:8px 28px;border-bottom:1px solid #E4DED3;display:flex;flex-wrap:wrap;gap:12px;z-index:2}
nav a{color:#2F6F68;text-decoration:none;font-size:12px}main{padding:8px 28px 40px;max-width:1280px}
section{background:#fff;border:1px solid #E4DED3;border-radius:8px;padding:14px 18px;margin:14px 0}
h2{font-size:15px;margin:0 0 10px}table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid #EFEAE1;padding:4px 6px;text-align:left;vertical-align:top}th{color:#7A7468;font-weight:600;background:#FBFAF7}
td.n{text-align:right;font-variant-numeric:tabular-nums}.ok{color:#2F6F68}.fail{color:#9B1C1C}.warn{color:#B45309}
.kpis{display:flex;gap:10px;flex-wrap:wrap}.kpi{border:1px solid #E4DED3;border-radius:6px;padding:8px 12px;min-width:150px}
.kpi b{font-size:20px;display:block}.scroll{overflow-x:auto}.lg span{display:inline-block;margin-right:12px}.lg i{display:inline-block;width:10px;height:10px;margin-right:4px}
ul{margin:4px 0 0 18px;padding:0}svg text{font-family:inherit}
.op{border-top:1px solid #EFEAE1;padding:10px 0}.op:first-of-type{border-top:0}.op h3{font-size:13px;margin:0 0 6px}
.op li{margin:2px 0}.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#EFEAE1;max-width:420px;margin:4px 0 6px}.bar i{display:block;height:100%}
"""


def _sec(i: int, body: str) -> str:
    return f"<section id='s{i}'><h2>{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫'[i-1]} {SECTIONS[i-1]}</h2>{body}</section>"


def _f(v: Any, d: int = 1) -> str:
    return "—" if v is None else f"{v:,.{d}f}" if isinstance(v, (int, float)) else escape(str(v))


def _short(v: str) -> str:
    return v.replace("cam-rec-", "")


def _overview(o: dict[str, Any]) -> str:
    ob, ax = o.get("objective") or {}, o.get("axes") or {}
    rows = [
        ("Target SoC", o["target_soc"]), ("Project", o["project"]), ("Scenario Type", o["scenario_type"]),
        ("Exploration run", f"{o['run_id']} · {o['run_title']} · {o['run_created_at'][:19]}"),
        ("DVFS table", f"{o['dvfs_table_ref']}{' (SAMPLE — 사내 table 교체 필요)' if o['sample_dvfs'] else ''}"),
        ("SW 기준", f"이전 과제 SW timing · 목적 통계 {ob.get('statistic')} · 증가 ×{ob.get('runtime_scale')}"),
        ("탐색 축", f"SW 통계 {ax.get('statistics')} · SW 증가 {ax.get('runtime_scales')} · DVFS +{ax.get('dvfs_headroom_levels')} level · "
                   f"compression {((ax.get('compression') or {}).get('modes'))} (≤{(ax.get('compression') or {}).get('max_buffers')} buffer)"),
        ("추천 규칙", f"eligible 조합 중 최저 total power (동률 {ob.get('tie_pct')}% → BW → 변경 수)"),
        ("Engine", o["engine_rev"]),
    ]
    body = "<table>" + "".join(f"<tr><th style='width:160px'>{escape(k)}</th><td>{escape(str(v))}</td></tr>" for k, v in rows) + "</table>"
    return body + "<p class='warn'><b>모델 한계</b></p><ul>" + "".join(f"<li>{escape(x)}</li>" for x in o["model_limits"]) + "</ul>"


def _spec(s: dict[str, Any]) -> str:
    rng = s["power_range_mw"]
    k = (f"<div class='kpis'><div class='kpi'>탐색 scenario<b>{s['explored']}</b></div>"
         f"<div class='kpi'>spec 만족<b class='ok'>{s['spec_ok']}</b></div>"
         f"<div class='kpi'>spec 미달<b class='fail'>{s['spec_fail']}</b></div>"
         f"<div class='kpi'>등록 예측 power<b>{_f(rng[0], 0) if rng else '—'}–{_f(rng[1], 0) if rng else ''}</b>mW</div></div>")
    if s["failed"]:
        k += "<table style='margin-top:10px'><tr><th>미달 scenario</th><th>원인</th></tr>" + "".join(
            f"<tr><td>{escape(_short(f['variant_id']))}</td><td>{escape('; '.join(f['reasons']))}</td></tr>" for f in s["failed"]) + "</table>"
    if s["errors"]:
        k += f"<p class='fail'>계산 실패 {len(s['errors'])}: " + escape(", ".join(e["variant_id"] for e in s["errors"][:8])) + "</p>"
    return k


def _opinions(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "<p class='meta'>분류 정보 없음 (이전 형식 snapshot) — 보고서를 재생성하면 표시됩니다.</p>"
    h = ("<p class='meta'>분류: 30 fps(해상도 × EIS × codec) · 60 fps · 고속(≥100 fps) · Heavy(Pro/Portrait/Dual/Triple). "
         "의견은 이 snapshot의 예측 수치 (등록 또는 추천)에서 규칙으로 생성 — 실측 근거가 아님.</p>")
    for b in blocks:
        rng = b.get("power_range_mw")
        sh = b.get("share_pct") or {}
        h += (f"<div class='op'><h3>{escape(b['title'])} <span class=meta>· {escape(b['scope'])} · "
              f"spec {b['spec_ok']}/{b['count']}{f' · {rng[0]:,.0f}–{rng[1]:,.0f} mW' if rng else ''}</span></h3>")
        if sh:
            h += ("<div class='bar'>" + "".join(f"<i style='width:{v:.1f}%;background:{C[c]}' title='{k} {v:.0f}%'></i>"
                  for (k, v), c in zip(sh.items(), ("cpu", "hw", "bw"), strict=False)) + "</div>")
        h += "<ul>" + "".join(f"<li>{escape(o)}</li>" for o in b["opinions"]) + "</ul>"
        h += f"<details><summary>variant {len(b['variants'])}</summary><span class=meta>{escape(', '.join(_short(v) for v in b['variants']))}</span></details></div>"
    return h


def _scenarios(rows: list[dict[str, Any]]) -> str:
    h = ("<div class='scroll'><table><tr><th>Scenario</th><th>fps</th><th>EIS</th><th>판정</th><th>Total mW</th>"
         "<th>CPU</th><th>IP</th><th>IP BW</th><th>CPU BW</th><th>BW MB/s</th><th>range mW (min–max)</th><th>Compression</th><th>DVFS level</th><th>검증</th></tr>")
    for r in rows:
        p, d = r["power"], r["distribution"]["total_mw"]
        ver = r.get("verified") or {}
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{'ON' if r['eis_on'] else '—'}</td>"
              f"<td class={'ok' if r['spec_ok'] else 'fail'}>{'OK' if r['spec_ok'] else 'FAIL'}</td>"
              f"<td class=n><b>{_f(p.get('total_mw'))}</b></td><td class=n>{_f(p.get('cpu_mw'))}</td><td class=n>{_f(p.get('hw_mw'))}</td>"
              f"<td class=n>{_f(p.get('bw_ip_mw', p.get('bw_mw')))}</td><td class=n>{_f(p.get('bw_cpu_mw'))}</td><td class=n>{_f(r['bw_mbs'],0)}</td><td class=n>{_f(d.get('min'),0)}–{_f(d.get('max'),0)}</td>"
              f"<td>{len(r['compression'])} buf{' <span class=warn>lossy</span>' if r.get('lossy') and r['compression'] else ''}</td>"
              f"<td>{escape(', '.join(f'{k}:L{v}' for k, v in sorted(r['dvfs'].items())))}</td>"
              f"<td>{'✓ ' + _f(ver.get('delta_pct'), 2) + '%' if ver.get('ok') else ('✗' if ver else '—')}</td></tr>")
    return h + "</table></div>"


def _clocks(clocks: list[dict[str, Any]]) -> str:
    nodes = sorted({c["node"] for c in clocks}, key=lambda n: (min(("rt", "nrt", "post", "output").index(c["stage"]) if c["stage"] in ("rt", "nrt", "post", "output") else 9 for c in clocks if c["node"] == n), n))
    variants = list(dict.fromkeys(c["variant_id"] for c in clocks))
    cell = {(c["variant_id"], c["node"]): c for c in clocks}
    h = "<p class='meta'>셀 = 필요 → 설정 MHz · level · 전압. CAM 등 domain level은 scenario별로 다를 수 있음. 색 = headroom (진할수록 여유 적음)</p>"
    h += "<div class='scroll'><table><tr><th>Scenario</th>" + "".join(f"<th>{escape(n.upper())}</th>" for n in nodes) + "</tr>"
    for v in variants:
        h += f"<tr><td>{escape(_short(v))}</td>"
        for n in nodes:
            c = cell.get((v, n))
            if not c:
                h += "<td></td>"
                continue
            hr = c["headroom_pct"]
            bg = "#fff" if hr is None else f"rgba(47,111,104,{max(0.06, min(0.5, 0.5 - hr / 200)):.2f})"
            lv = f"L{c['level']}" if c["level"] is not None else ""
            h += (f"<td style='background:{bg};white-space:nowrap'>{_f(c['required_mhz'],0)}→{_f(c['set_mhz'],0)}"
                  f"<br><span class=meta>{lv} {_f(c['voltage_mv'],0)}mV</span></td>")
        h += "</tr>"
    return h + "</table></div>"


def _domains(rows: list[dict[str, Any]]) -> str:
    doms = sorted({r["domain"] for r in rows})
    variants = list(dict.fromkeys(r["variant_id"] for r in rows if r["spec_ok"]))
    cell = {(r["variant_id"], r["domain"]): r for r in rows}
    h = ("<p class='meta'>DVFS domain별 선택 level (spec 만족 scenario). 셀 = level · MHz · mV / 필요 max MHz (driver IP). "
         "색이 진할수록 headroom 적음. CAM level은 scenario마다 다르게 설정 가능.</p>")
    h += "<div class='scroll'><table><tr><th>Scenario</th>" + "".join(f"<th>{escape(d)}</th>" for d in doms) + "</tr>"
    for v in variants:
        h += f"<tr><td>{escape(_short(v))}</td>"
        for d in doms:
            c = cell.get((v, d))
            if not c:
                h += "<td></td>"
                continue
            hr = c["headroom_pct"]
            bg = "#fff" if hr is None else f"rgba(47,111,104,{max(0.06, min(0.55, 0.55 - hr / 150)):.2f})"
            h += (f"<td style='background:{bg};white-space:nowrap'><b>L{c['level']}</b> {_f(c['speed_mhz'],0)} MHz · {_f(c['voltage_mv'],0)} mV"
                  f"<br><span class=meta>필요 {_f(c['required_mhz'],0)} ({escape(str(c['driver'] or '-'))}) · +{_f(hr,0)}%</span></td>")
        h += "</tr>"
    return h + "</table></div>"


def _fail_margins(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    h = f"<h3 style='font-size:13px;margin:14px 0 4px'>spec 미달 {len(rows)}건 (margin 음수)</h3><table><tr><th>Scenario</th><th>fps</th><th>stage</th><th>SW / P</th><th>필요 단축</th><th>병목</th></tr>"
    for r in rows:
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{escape(r['stage'].upper())}</td>"
              f"<td class='n fail'>{_f(r['sw_share_pct'],0)}%</td><td class=n>{_f(-r['slack_ms'],2)} ms</td>"
              f"<td>{escape(str(r['bottleneck']))} {_f(r['bottleneck_ms'],1)} ms</td></tr>")
    return h + "</table>"


def _boxes(rows: list[dict[str, Any]]) -> str:
    rows = [r for r in rows if r["spec_ok"]]
    out = "<p class='meta'>spec 만족 scenario만 표시 (미달은 ②). 막대 = min–max, 상자 = p25–p75, 굵은 선 = median</p>"
    for key, label, unit in (("total_mw", "Total power", "mW"), ("cpu_mw", "CPU (SW)", "mW"), ("hw_mw", "IP (HW core)", "mW"),
                             ("bw_ip_mw", "IP BW", "mW"), ("bw_cpu_mw", "CPU BW", "mW"),
                             ("bw_mbs", "BW", "MB/s")):
        out += f"<h3 style='font-size:13px;margin:12px 0 4px'>{label} ({unit}) — box = 조합 × SW 통계 · ◆ = 등록 예측</h3>" + _box_svg(rows, key)
    return out


_KEY_COLOR = {"total_mw": "total", "cpu_mw": "cpu", "hw_mw": "hw", "bw_mw": "bw", "bw_ip_mw": "bw", "bw_cpu_mw": "bwcpu", "bw_mbs": "bw"}


def _box_svg(rows: list[dict[str, Any]], key: str) -> str:
    lw, W, rh = 190, 760, 18
    vals = [r["distribution"][key] for r in rows if r["distribution"].get(key)]
    if not vals:
        return ""
    hi = max(v["max"] for v in vals) * 1.05 or 1
    k = (W - lw - 70) / hi
    H = len(rows) * rh + 24
    g = [f"<svg width='{W}' height='{H}' viewBox='0 0 {W} {H}'>"]
    for t in range(6):
        x = lw + t * (W - lw - 70) / 5
        g.append(f"<line x1='{x:.1f}' x2='{x:.1f}' y1='0' y2='{H-16}' stroke='{C['line']}'/><text x='{x:.1f}' y='{H-4}' font-size='10' fill='{C['mute']}' text-anchor='middle'>{hi*t/5:,.0f}</text>")
    for i, r in enumerate(rows):
        d = r["distribution"].get(key)
        y = i * rh + 4
        g.append(f"<text x='{lw-6}' y='{y+11}' font-size='11' text-anchor='end' fill='{C['ink']}'>{escape(_short(r['variant_id']))}</text>")
        if not d:
            continue
        col = C[_KEY_COLOR[key]] if r["spec_ok"] else C["fail"]
        g.append(f"<line x1='{lw+d['min']*k:.1f}' x2='{lw+d['max']*k:.1f}' y1='{y+7}' y2='{y+7}' stroke='{col}'/>")
        g.append(f"<rect x='{lw+d['p25']*k:.1f}' y='{y+1}' width='{max(1,(d['p75']-d['p25'])*k):.1f}' height='12' fill='{col}' fill-opacity='.25' stroke='{col}'/>")
        g.append(f"<line x1='{lw+d['median']*k:.1f}' x2='{lw+d['median']*k:.1f}' y1='{y+1}' y2='{y+13}' stroke='{col}' stroke-width='2'/>")
        mk = r["bw_mbs"] if key == "bw_mbs" else r["power"].get(key)
        if mk is not None:
            x = lw + mk * k
            g.append(f"<path d='M{x:.1f},{y} l5,7 l-5,7 l-5,-7z' fill='#CC3311' stroke='#fff' stroke-width='.8'/>")
        g.append(f"<text x='{W-66}' y='{y+11}' font-size='10' fill='{C['mute']}'>{d['min']:,.0f}–{d['max']:,.0f}</text>")
    g.append("</svg>")
    return "<div class='scroll'>" + "".join(g) + "</div>"


def _split(rows: list[dict[str, Any]]) -> str:
    lw, W, rh = 190, 760, 18
    ok = [r for r in rows if r["power"].get("total_mw")]
    hi = max((r["power"]["total_mw"] for r in ok), default=1) * 1.05
    k = (W - lw - 120) / hi
    H = len(ok) * rh + 8
    g = [f"<div class='lg'><span><i style='background:{C['cpu']}'></i>CPU (SW)</span><span><i style='background:{C['bwcpu']}'></i>CPU BW</span>"
         f"<span><i style='background:{C['hw']}'></i>IP (HW core)</span><span><i style='background:{C['bw']}'></i>IP BW</span></div>",
         f"<div class='scroll'><svg width='{W}' height='{H}'>"]
    for i, r in enumerate(ok):
        p, y, x = r["power"], i * rh + 4, float(lw)
        g.append(f"<text x='{lw-6}' y='{y+11}' font-size='11' text-anchor='end'>{escape(_short(r['variant_id']))}</text>")
        parts = _parts(p)
        for key, val in parts:
            w = val * k
            g.append(f"<rect x='{x:.1f}' y='{y+1}' width='{max(0,w):.1f}' height='12' fill='{C[key]}'/>")
            x += w
        t = p["total_mw"]
        share = " · ".join(f"{lbl} {100*v/t:.0f}%" for lbl, v in zip(("CPU", "CPU BW", "IP", "IP BW"), [v for _, v in parts], strict=True))
        g.append(f"<text x='{x+4:.1f}' y='{y+11}' font-size='10' fill='{C['mute']}'>{t:,.0f} mW · {share}</text>")
    g.append("</svg></div>")
    return "".join(g)


def _parts(p: dict[str, Any]) -> list[tuple[str, float]]:
    """CPU, CPU BW, IP core, IP BW (engine rev 1 predictions: all BW as IP BW)."""
    bw_ip = p.get("bw_ip_mw", p.get("bw_mw")) or 0.0
    return [("cpu", p.get("cpu_mw") or 0.0), ("bwcpu", p.get("bw_cpu_mw") or 0.0),
            ("hw", p.get("hw_mw") or 0.0), ("bw", bw_ip)]


def _compression(rows: list[dict[str, Any]], scen: list[dict[str, Any]]) -> str:
    saved = [(r["variant_id"], (r["baseline_bw_mbs"] or 0) - (r["bw_mbs"] or 0), (r["baseline_total_mw"] or 0) - (r["power"].get("total_mw") or 0))
             for r in scen if r["spec_ok"] and r["baseline_bw_mbs"] is not None]
    tot_bw = sum(s[1] for s in saved)
    h = (f"<div class='kpis'><div class='kpi'>등록 예측 BW 절감 합<b>{tot_bw:,.0f}</b>MB/s</div>"
         f"<div class='kpi'>scenario 평균<b>{(tot_bw/len(saved) if saved else 0):,.0f}</b>MB/s</div></div>")
    h += ("<table style='margin-top:10px'><tr><th>Buffer</th><th>Mode</th><th>ratio</th><th>출처</th><th>IP 지원</th><th>적용/대상</th>"
          "<th>ΔMB/s (선택, 합)</th><th>ΔmW (선택, 합)</th><th>ΔMB/s (전체 적용 시)</th></tr>")
    for c in rows:
        h += (f"<tr><td>{escape(c['buffer'])}</td><td>{escape(str(c['mode']))}{' <span class=warn>lossy</span>' if c['lossy'] else ''}</td>"
              f"<td class=n>{_f(c['ratio'],2)}</td><td class={'warn' if c['ratio_source']=='assumed' else ''}>{escape(str(c['ratio_source']))}</td>"
              f"<td>{escape(str(c['support']))}</td><td class=n>{c['selected']}/{c['variants']}</td>"
              f"<td class=n>{_f(c['selected_delta_mbs'],0)}</td><td class=n>{_f(c['selected_delta_mw'],1)}</td><td class=n>{_f(c['delta_mbs'],0)}</td></tr>")
    return h + "</table>"


def _margins(rows: list[dict[str, Any]]) -> str:
    h = ("<p class='meta'>SW timing margin = (P − SW(runtime+latency) − IP overhead − HW@set clock) / P, NRT·Post-NRT 중 최소, 목적 통계 기준</p>"
         "<table><tr><th>#</th><th>Scenario</th><th>fps</th><th>stage</th><th>margin</th><th>SW / P</th><th>병목 task</th><th>SW 증가 허용</th><th>권고</th></tr>")
    for i, r in enumerate(rows, 1):
        h += (f"<tr><td>{i}</td><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{escape(r['stage'].upper())}</td>"
              f"<td class='n {'fail' if r['margin_pct'] < 0 else ''}'><b>{_f(r['margin_pct'],1)}%</b><br><span class=meta>{_f(r['slack_ms'],2)} ms</span></td>"
              f"<td class=n>{_f(r['sw_share_pct'],0)}%</td><td>{escape(str(r['bottleneck']))} {_f(r['bottleneck_ms'],1)} ms ({_f(r['bottleneck_share_pct'],0)}%)</td>"
              f"<td class=n>{'×'+_f(r['growth_tolerance'],1) if r['growth_tolerance'] else '—'}</td>"
              f"<td><ul>{''.join(f'<li>{escape(x)}</li>' for x in r['recommendations'])}</ul></td></tr>")
    return h + "</table>"


def _history(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='meta'>직전 등록 예측 없음 (첫 등록)</p>"
    h = "<table><tr><th>Scenario</th><th>ΔP</th><th>원인 (카테고리)</th><th>주요 항목</th><th>입력 변경</th></tr>"
    for r in rows:
        cats = ", ".join(f"{k} {v:+.1f}" for k, v in list(r["by_category"].items())[:4])
        top = ", ".join(f"{t['item']} {t['delta_mw']:+.1f}" for t in r["top"])
        ctx = ", ".join(f"{c['item']}: {c['old']}→{c['new']}" for c in r["context"][:5])
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n><b>{r['delta_mw']:+.1f}</b> mW<br><span class=meta>{_f(r['delta_pct'],1)}%</span></td>"
              f"<td>{escape(cats)}</td><td>{escape(top)}</td><td>{escape(ctx)}</td></tr>")
    return h + "</table>"


def _appendix(a: dict[str, Any]) -> str:
    c = a.get("counts") or {}
    h = "<table>" + "".join(f"<tr><th style='width:200px'>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in c.items()) + "</table>"
    h += f"<p><b>등록 예측</b> ({len(a['prediction_ids'])}): <span class=meta>{escape(', '.join(a['prediction_ids'][:80]))}</span></p>"
    if a["warnings"]:
        h += "<details><summary>경고 " + str(len(a["warnings"])) + "</summary><ul>" + "".join(f"<li>{escape(w)}</li>" for w in a["warnings"]) + "</ul></details>"
    return h
