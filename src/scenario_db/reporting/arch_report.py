"""Architecture review report: frozen snapshot from an exploration run + HTML render."""

from __future__ import annotations

import hashlib
import re
from html import escape
from typing import Any

from scenario_db.reporting.arch_conclusion import build_conclusion, model_limits, run_lineage
from scenario_db.reporting.arch_opinions import build_opinions, classify
from scenario_db.reporting.reason_text import diagnose, explain_all
from scenario_db.reporting.clock_section import clock_block

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

def build_snapshot(
    run: dict[str, Any],
    predictions: dict[tuple[str, str], dict[str, Any]],
    changes: dict[tuple[str, str], dict[str, Any]],
    calibration: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """run: exploration run row as dict; predictions: variant -> current prediction row dict;
    changes: variant -> attribution vs the superseded prediction;
    calibration: ``arch_conclusion.calibration_row`` per measured variant (frozen with the snapshot).
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
            "status": v.get("status") or {},
            "power_coverage": (v.get("coverage") or {}).get("power_coverage")
            or ("partial" if (v.get("coverage") or {}).get("zero_power_ips") else None),
            "zero_power_ips": (v.get("coverage") or {}).get("zero_power_ips") or [],
            "reasons_explained": explain_all(compact_reasons(v["spec_reasons"]), v["fps"]),
            "period_ms": v.get("period_ms") or (1000.0 / v["fps"] if v.get("fps") else None),
            "latency": (v.get("objective_slice") or {}).get("latency"),
            "intervals": (v.get("objective_slice") or {}).get("intervals"),
            "prediction_id": (pred or {}).get("id"), "selection_rule": (pred or {}).get("selection_rule"),
            "power": chosen.get("power") or {k: rec.get(k) for k in ("total_mw", "cpu_mw", "hw_mw", "bw_mw", "bw_ip_mw", "bw_cpu_mw")},
            "bw_mbs": chosen.get("bw_mbs", rec.get("bw_mbs")),
            "baseline_bw_mbs": (v.get("baseline") or {}).get("bw_mbs"),
            "baseline_total_mw": (v.get("baseline") or {}).get("total_mw"),
            "compression": chosen.get("compression", rec.get("compression", [])),
            # compression-only effect: buffer deltas are port-independent and additive (same SW/DVFS)
            **_compression_only(v.get("buffers") or [], chosen.get("compression", rec.get("compression", []))),
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
                        "growth_tolerance_fixed": m.get("growth_tolerance_fixed"),
                        "recommendations": m.get("recommendations", [])})
    margins.sort(key=lambda r: (r["margin_pct"], -r["sw_share_pct"]))

    history = []
    for (sid, vid), ch in changes.items():
        history.append({"scenario_id": sid, "variant_id": vid, "delta_mw": ch["delta_mw"], "delta_pct": ch["delta_pct"],
                        "by_category": ch["by_category"], "top": ch["factors"][:4],
                        "context": [_ctx(c) for c in ch["context_changes"] if c["item"] != "exploration_run_ref"]})

    options = []
    for v in variants:
        pred = predictions.get((v["scenario_id"], v["variant_id"]))
        po = ((pred or {}).get("metrics") or {}).get("power_options") if pred else v.get("power_options")
        if not po or po.get("status") != "ok":
            continue
        ranked = [r for r in po.get("results") or [] if r.get("delta_mw") is not None]
        items = {i["key"]: i for d in po.get("dimensions") or [] for i in d.get("items") or []}
        singles = [r for r in ranked if len(r["items"]) == 1]
        if not ranked:
            continue  # spec-fail variant: no comparable (recommended) power
        options.append({
            "scenario_id": v["scenario_id"], "variant_id": v["variant_id"], "fps": v["fps"],
            "base_total_mw": (v.get("recommended") or {}).get("total_mw"),
            "best": next(({"key": r["key"], "labels": r["labels"], "delta_mw": r["delta_mw"], "delta_pct": r["delta_pct"],
                           "by_category": r["attribution"]["by_category"], "delta_latency_ms": r.get("delta_latency_ms"),
                           "iq_eval": r.get("iq_eval"), "kinds": r.get("kinds")}
                          for r in ranked if r["spec_ok"] and r["delta_mw"] < 0), None),
            "singles": [{"key": r["key"], "label": r["labels"][0], "delta_mw": r["delta_mw"], "delta_pct": r["delta_pct"],
                         "spec_ok": r["spec_ok"], "kind": (items.get(r["items"][0]) or {}).get("kind"),
                         "delta_latency_ms": r.get("delta_latency_ms"), "iq_eval": r.get("iq_eval")} for r in singles],
            "sets": len(ranked), "notes": po.get("notes") or [],
        })

    power_rows = [r for r in rows if r["spec_ok"] and r["power"].get("total_mw") is not None]
    totals = [r["power"]["total_mw"] for r in power_rows]
    lineage, mixed = run_lineage(run)
    snap = {
        "overview": {
            "run_id": run["id"], "run_title": run["title"], "run_created_at": str(run.get("created_at") or ""),
            "target_soc": run.get("soc_ref"), "project": run.get("project_ref"),
            "scenario_type": run["scenario_type"], "dvfs_table_ref": run.get("dvfs_table_ref"),
            "sample_dvfs": sample_dvfs, "objective": run["spec"].get("objective"),
            "axes": run["spec"].get("axes"), "constraints": run["spec"].get("constraints"),
            "engine_rev": run.get("engine_rev"), "model_lineage": lineage, "model_limits": model_limits(lineage, mixed),
        },
        "spec_summary": {
            # requested = evaluated + calc_failed; "explored" kept as the evaluated count (old snapshots)
            "requested": len(variants) + len(run.get("errors") or []),
            "evaluated": len(variants), "calc_failed": len(run.get("errors") or []),
            "partial": bool(run.get("errors")),
            "power_partial": sum(1 for r in rows if r["power_coverage"] in ("partial", "none")),
            "explored": len(variants), "spec_ok": len(ok), "spec_fail": len(variants) - len(ok),
            "failed": [{"variant_id": v["variant_id"], "reasons": compact_reasons(v["spec_reasons"])[:3],
                        "explained": explain_all(compact_reasons(v["spec_reasons"]), v["fps"])}
                       for v in variants if not v["spec_ok"]],
            "errors": run.get("errors") or [],
            "power_range_mw": [round(min(totals), 1), round(max(totals), 1)] if totals else None,
            "power_sources": {"registered": sum(bool(r["prediction_id"]) for r in power_rows),
                              "recommended": sum(not r["prediction_id"] for r in power_rows)},
        },
        "opinions": build_opinions(rows, domains, sample_dvfs=sample_dvfs,
                                   measured={(c["scenario_id"], c["variant_id"]) for c in calibration or []
                                             if (c.get("origin") == "physical_capture" if c.get("origin") else not c.get("synthetic"))
                                             and c["fit"]["worst_delta_pct"] is not None}, options=options),
        "scenarios": rows,
        "clocks": clocks,
        "compression": comp_rows,
        "power_options": options,
        "sw_margin_top5": [m for m in margins if m["spec_ok"]][:5],
        "sw_margin_fail": [m for m in margins if not m["spec_ok"]],
        "domains": domains,
        "history": history,
        "appendix": {
            "counts": run.get("summary"),
            "prediction_ids": sorted(p["id"] for p in predictions.values()),
            "warnings": sorted({w for v in variants for w in (v.get("warnings") or [])})[:40],
        },
        "calibration": list(calibration or []),
    }
    snap["conclusion"] = build_conclusion(snap)
    return snap


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
        _sec(1, _conclusion(snap.get("conclusion"))),
        _sec(2, _overview(o)),
        _sec(3, _spec(s)),
        _sec(4, _calibration(snap.get("calibration") or []) + clock_block(snap.get("clock_residency") or [])),
        _sec(5, _opinions(snap.get("opinions") or [])),
        _sec(6, _scenarios(snap["scenarios"])),
        _sec(7, _latency(snap["scenarios"])),
        _sec(8, _domains(snap.get("domains") or []) + "<details><summary>IP별 상세 (필요 → 설정 MHz)</summary>"
             + _clocks([c for c in snap["clocks"] if (c["scenario_id"], c["variant_id"]) in
                        {(r["scenario_id"], r["variant_id"]) for r in snap["scenarios"] if r["spec_ok"]}])
             + "</details>"),
        _sec(9, _boxes(snap["scenarios"])),
        _sec(10, _split(snap["scenarios"])),
        _sec(11, _compression(snap["compression"], snap["scenarios"])),
        _sec(12, _power_options(snap.get("power_options") or [])),
        _sec(13, _margins(snap["sw_margin_top5"]) + _fail_margins(snap.get("sw_margin_fail") or [])),
        _sec(14, _history(snap["history"])),
        _sec(15, _appendix(snap["appendix"])),
        "</main></body></html>",
    ]
    return "".join(parts)


def html_sha256(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


SECTIONS = ["결론", "개요", "Spec 만족", "실측 대조", "분류별 검토 의견", "Scenario 요약", "Latency · 출력 간격", "IP 필요 clock", "Power·BW 분포", "CPU/IP/BW",
            "Compression 절감", "Power option (IQ 평가 대상)", "SW margin Top5", "변경 이력", "부록"]

_CSS = """
.meta{font-size:13.5px}h3{font-size:16px}
body{font:15px/1.6 -apple-system,'Segoe UI','Malgun Gothic',sans-serif;color:#23262E;background:#FBFAF7;margin:0}
header{padding:20px 32px;border-bottom:1px solid #E4DED3;background:#fff}h1{margin:0;font-size:24px}
.meta{color:#7A7468;margin-top:4px}nav{position:sticky;top:0;background:#FBFAF7;padding:8px 28px;border-bottom:1px solid #E4DED3;display:flex;flex-wrap:wrap;gap:12px;z-index:2}
nav a{color:#2F6F68;text-decoration:none;font-size:13.5px}main{padding:8px 32px 48px;max-width:1920px}
section{background:#fff;border:1px solid #E4DED3;border-radius:10px;padding:18px 24px;margin:16px 0}
h2{font-size:19px;margin:0 0 12px}table{border-collapse:collapse;width:100%;font-size:14px}
th,td{border-bottom:1px solid #EFEAE1;padding:6px 8px;text-align:left;vertical-align:top}th{color:#7A7468;font-weight:600;background:#FBFAF7}
td.n{text-align:right;font-variant-numeric:tabular-nums}.ok{color:#2F6F68}.fail{color:#9B1C1C}.warn{color:#B45309}
.kpis{display:flex;gap:12px;flex-wrap:wrap}.kpi{border:1px solid #E4DED3;border-radius:8px;padding:10px 16px;min-width:170px}
.kpi b{font-size:26px;display:block}.scroll{overflow-x:auto}.lg span{display:inline-block;margin-right:12px}.lg i{display:inline-block;width:10px;height:10px;margin-right:4px}
ul{margin:4px 0 0 18px;padding:0}svg text{font-family:inherit}
.op{border-top:1px solid #EFEAE1;padding:14px 0}.op:first-of-type{border-top:0}.op h3{font-size:16px;margin:0 0 8px}
@media print{nav{display:none}body{background:#fff}main{max-width:none;padding:0 10mm}section{border:0;padding:6px 0}tr,.kpi,.op h3,h2{break-inside:avoid}h2,.op h3{break-after:avoid}
details{display:block}details>summary{display:none}.scroll{overflow:visible}
header{border:0;padding:0 10mm 4mm}@page{size:A4 landscape;margin:12mm}}
.op li{margin:2px 0}.bt{font-size:11.5px;padding:0 6px;border-radius:3px;margin-right:2px}.b-meas{background:#E5F2EC;color:#1E6446}.b-calc{background:#E7ECF5;color:#26406B}.b-asm{background:#FDF0DC;color:#9A5B0B}.b-in{background:#EFEAE1;color:#5A5448}.bar{display:flex;height:8px;border-radius:4px;overflow:hidden;background:#EFEAE1;max-width:420px;margin:4px 0 6px}.bar i{display:block;height:100%}
.cause{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:12px;margin:12px 0}
.cause>div{border:1px solid #E4DED3;border-left:5px solid #9B1C1C;border-radius:8px;padding:10px 14px;background:#FFFCFA}
.cause h4{margin:0 0 4px;font-size:15.5px}.cause .sev{font-weight:700;color:#9B1C1C}.cause ol{margin:4px 0 0 20px;padding:0}
.focus{background:#F4F8F6;border-radius:6px;padding:6px 10px;margin:6px 0;font-size:14px}.focus b{color:#174D47}
.q4{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:8px}
.q4>div{border:1px solid #E4DED3;border-radius:8px;padding:10px 14px;background:#fff}
.q4 h4{margin:0 0 6px;font-size:14.5px;display:flex;align-items:center;gap:8px}.q4 h4 i{display:inline-block;width:10px;height:10px;border-radius:2px}
.q4 ul{margin:0 0 0 18px}.q4 li{margin:4px 0}
.q-review{border-top:3px solid #4A5160!important}.q-risk{border-top:3px solid #B42318!important;background:#FFFBFA!important}
.q-mit{border-top:3px solid #B45309!important}.q-opt{border-top:3px solid #2F6F68!important;background:#FAFDFB!important}
@media(max-width:1100px){.q4{grid-template-columns:1fr}}
@media print{.q4{grid-template-columns:1fr 1fr}}
"""


def _sec(i: int, body: str) -> str:
    return f"<section id='s{i}'><h2>{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮'[i-1]} {SECTIONS[i-1]}</h2>{body}</section>"


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


_GRADE_CLASS = {"A": "ok", "B": "warn", "C": "fail"}


def _conclusion(c: dict[str, Any] | None) -> str:
    if not c:
        return "<p class='meta'>이 snapshot에는 결론이 없음 (이전 형식) — 재생성하면 표시</p>"
    conf = c["confidence"]
    h = (f"<p style='font-size:17px'><b>{escape(c['headline'])}</b></p>"
         f"<div class='kpis'><div class='kpi'>신뢰도<b class='{_GRADE_CLASS[conf['grade']]}'>{conf['grade']}</b>"
         f"<span class=meta>{escape(conf['meaning'])}</span></div></div>")
    if conf["reasons"]:
        h += "<ul>" + "".join(f"<li class=meta>{escape(r)}</li>" for r in conf["reasons"]) + "</ul>"
    h += "<h3 style='margin:14px 0 4px'>주요 리스크</h3>"
    h += ("<ol>" + "".join(f"<li><b>{escape(r['title'])}</b> — {escape(r['detail'])}</li>" for r in c["risks"]) + "</ol>"
          if c["risks"] else "<p class=meta>식별된 리스크 없음</p>")
    h += "<h3 style='margin:14px 0 4px'>권고 조치</h3>"
    if not c["actions"]:
        return h + "<p class=meta>권고 조치 없음</p>"
    h += "<table><tr><th>조치</th><th>대상</th><th>ΔPower</th><th>근거</th><th>필요 검증</th></tr>"
    for a in c["actions"]:
        d = f"{a['delta_mw']:+.0f} mW ({_f(a['delta_pct'], 1)}%)" if a["delta_mw"] is not None else "—"
        h += (f"<tr><td>{escape(a['action'])}</td><td>{escape(_short(str(a['target'])))}</td><td class=n>{d}</td>"
              f"<td>{escape(a['basis'])}</td><td>{escape(a['check'])}</td></tr>")
    return h + "</table>"


_CAT_LABEL = {"cpu": "CPU", "ip": "IP", "bw": "BW", "other": "기타(미모델)"}


def _calibration(rows: list[dict[str, Any]]) -> str:
    h = ("<p class='meta'>이 보고서의 등록 예측을 실측 rail(CPU · IP · BW(MIF·DRAM) · 기타)과 비교. 판정은 total이 아닌 "
         "구성 최대 |Δ| 기준(≤10% 녹색 · ≤25% 주황 · 초과 빨강). 합성 fixture는 모델 검증 근거가 아님.</p>")
    if not rows:
        return h + "<p class='warn'>실측 대조 가능한 variant 없음 — 이 보고서의 수치는 실측으로 검증되지 않았습니다.</p>"
    def origin(r: dict[str, Any]) -> str:
        return r.get("origin") or ("synthetic" if r["synthetic"] else "physical_capture")
    real = sum(1 for r in rows if origin(r) == "physical_capture")
    unknown = sum(1 for r in rows if origin(r) == "unknown")
    h += (f"<p>실측 {real}건 · 합성 {sum(1 for r in rows if origin(r) == 'synthetic')}건"
          + (f" · <span class=warn>출처 미기록 {unknown}건 (정확도 근거 제외)</span>" if unknown else "") + "</p>")
    h += ("<table><tr><th>Scenario</th><th>측정</th><th>실측 mW</th><th>예측 mW</th><th>total Δ</th>"
          + "".join(f"<th>{_CAT_LABEL[c]} Δ</th>" for c in ("cpu", "ip", "bw")) + "<th>미모델 mW</th><th>판정</th></tr>")

    def cls(v: Any) -> str:
        return "" if v is None else "ok" if abs(v) <= 10 else "warn" if abs(v) <= 25 else "fail"

    for r in rows:
        by = {x["category"]: x for x in r["rows"]}
        fit = r["fit"]
        verdict = ("상쇄 (구성 오차)" if fit["offsetting"] else f"최대 {_CAT_LABEL.get(fit['worst_category'] or '', '—')} "
                   f"{_f(fit['worst_delta_pct'], 1)}%") if fit["worst_delta_pct"] is not None else "구성 비교 불가"
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td>"
              f"<td>{escape(str(r.get('measured_at') or '')[:10])}{' <b class=warn>합성</b>' if r['synthetic'] else (' <b class=warn>출처 미기록</b>' if origin(r) == 'unknown' else '')}</td>"
              f"<td class=n>{_f(r['measured_mw'], 1)}</td><td class=n>{_f(r['predicted_mw'], 1)}</td>"
              f"<td class='n {cls(r['delta_pct'])}'>{_f(r['delta_pct'], 1)}%</td>"
              + "".join(f"<td class='n {cls((by.get(c) or {}).get('delta_pct'))}'>{_f((by.get(c) or {}).get('delta_pct'), 1)}%</td>"
                        if (by.get(c) or {}).get("delta_pct") is not None else "<td class=meta>미모델</td>" for c in ("cpu", "ip", "bw"))
              + f"<td class=n>{_f(r.get('unmodeled_mw'), 1)}</td>"
              f"<td class='{cls(fit['worst_delta_pct']) if not fit['offsetting'] else 'warn'}'>{escape(verdict)}</td></tr>")
    return h + "</table>"


def _spec(s: dict[str, Any]) -> str:
    rng = s["power_range_mw"]
    failed_calc = s.get("calc_failed", len(s.get("errors") or []))
    k = (f"<div class='kpis'><div class='kpi'>요청 scenario<b>{s.get('requested', s['explored'] + failed_calc)}</b></div>"
         f"<div class='kpi'>평가 완료<b>{s.get('evaluated', s['explored'])}</b></div>"
         f"<div class='kpi'>spec 만족<b class='ok'>{s['spec_ok']}</b></div>"
         f"<div class='kpi'>spec 미달<b class='fail'>{s['spec_fail']}</b></div>"
         f"<div class='kpi'>계산 실패<b class='{'fail' if failed_calc else ''}'>{failed_calc}</b></div>"
         f"<div class='kpi'>등록 예측 power<b>{_f(rng[0], 0) if rng else '—'}–{_f(rng[1], 0) if rng else ''}</b>mW</div></div>")
    if s["failed"]:
        diag = []
        for f in s["failed"]:
            ex = f.get("explained") or [{"text": r, "action": "—", "raw": r, "code": "other"} for r in f["reasons"]]
            fps = None
            m = re.search(r"-(?:fhd|uhd|qhd|8k)(\d+)", f["variant_id"])
            if m:
                fps = float(m.group(1))
            per = next((float(x.group(1)) for e in ex for x in [re.search(r"주기 ([\d.]+) ms", e.get("text", ""))] if x), None)
            diag.append((f, ex, diagnose(ex, 1000.0 / per if per else fps)))
        groups: dict[str, list[tuple[Any, Any, Any]]] = {}
        for t in diag:
            sev = t[2]["severity"]
            bucket = "근소" if "(근소)" in sev else "중간" if "(중간)" in sev else "구조적" if "(구조적)" in sev else ""
            groups.setdefault(f"{t[2]['code']}{':' + bucket if bucket else ''}", []).append(t)
        k += "<h3 style='margin:16px 0 4px'>미달 원인 유형 — 무엇을 중점으로 볼 것인가</h3><div class='cause'>"
        for code, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            d0 = max(items, key=lambda t: t[2]["ratio"] or 0)[2]
            names = ", ".join(_short(t[0]["variant_id"]) for t in items)
            bucket = code.split(":")[1] if ":" in code else ""
            k += (f"<div><h4>{escape(d0['label'])}{f' · {bucket}' if bucket else ''} <span class=meta>· {len(items)}개</span></h4>"
                  f"<div class=meta>{escape(names)}</div>"
                  f"<div class='focus'><b>중점 검토</b> {escape(d0['focus'])}</div>"
                  f"<div>최대 심각도: <span class='sev'>{escape(d0['severity'])}</span></div>"
                  "<b style='font-size:14px'>최적화 권고 (효과 큰 순)</b><ol>" + "".join(f"<li>{escape(a)}</li>" for a in d0["actions"]) + "</ol></div>")
        k += "</div>"
        k += ("<h3 style='margin:16px 0 4px'>Scenario별 진단</h3><table><tr><th style='width:15%'>미달 scenario</th><th style='width:17%'>주 원인</th>"
              "<th style='width:14%'>부족 정도</th><th>권고 1순위</th><th style='width:24%'>함께 발생한 원인</th></tr>")
        for f, ex, d in diag:
            others = [e["text"] for e in ex if e.get("code") != d["code"] and e.get("code") != "interval"]
            k += (f"<tr><td><b>{escape(_short(f['variant_id']))}</b></td><td>{escape(d['label'].split(' — ')[0])}</td>"
                  f"<td class='fail'>{escape(d['severity'])}</td><td>{escape(d['actions'][0] if d['actions'] else d['focus'])}</td>"
                  f"<td class=meta title='{escape(' | '.join(e.get('raw', '') for e in ex), quote=True)}'>{escape(' · '.join(others) or '—')}</td></tr>")
        k += "</table><p class=meta>“함께 발생한 원인”에 마우스를 올리면 계산 엔진의 원문 사유가 보입니다. 출력 간격 미달은 위 원인의 결과라 생략.</p>"
    if s["errors"]:
        k += (f"<p class='fail'><b>부분 평가 결과</b> — 계산 실패 {len(s['errors'])}건은 위 집계에서 제외됨</p>"
              "<table><tr><th>Scenario</th><th>Stage</th><th>Category</th><th>원인</th></tr>"
              + "".join(f"<tr><td>{escape(_short(str(e.get('variant_id'))))}</td><td>{escape(str(e.get('stage') or '—'))}</td>"
                        f"<td>{escape(str(e.get('category') or '—'))}</td><td class=meta>{escape(str(e.get('error') or '')[:300])}</td></tr>"
                        for e in s["errors"][:20]) + "</table>")
    return k


_Q4 = (("review", "q-review", "#4A5160", "① 현재 검토"), ("risk", "q-risk", "#B42318", "② Risk"),
       ("mitigation", "q-mit", "#B45309", "③ Risk 감소 방안"), ("optimize", "q-opt", "#2F6F68", "④ 추가 최적화"))


def _opinions(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "<p class='meta'>분류 정보 없음 (이전 형식 snapshot) — 보고서를 재생성하면 표시됩니다.</p>"
    h = ("<p class='meta'>분류: 30 fps(해상도 × EIS × codec) · 60 fps · 고속(≥100 fps) · Heavy(Pro/Portrait/Dual/Triple). "
         "분류마다 ① 현재 검토 ② Risk ③ Risk 감소 방안 ④ 추가 최적화로 정리 — 모두 이 snapshot의 예측 수치에서 규칙으로 생성. 문장 앞 태그 = 근거: "
         + _basis_tag("실측") + "실측 대조 " + _basis_tag("산출") + "예측 계산값 " + _basis_tag("가정") + "가정 입력에 의존 "
         + _basis_tag("입력") + "catalog · 과제 데이터</p>")
    for b in blocks:
        rng = b.get("power_range_mw")
        sh = b.get("share_pct") or {}
        h += (f"<div class='op'><h3>{escape(b['title'])} <span class=meta>· {escape(b['scope'])} · "
              f"spec <b class='{'ok' if b['spec_ok'] == b['count'] else 'fail'}'>{b['spec_ok']}/{b['count']}</b>{f' · {rng[0]:,.0f}–{rng[1]:,.0f} mW' if rng else ''}</span></h3>")
        if sh:
            h += ("<div class='bar'>" + "".join(f"<i style='width:{v:.1f}%;background:{C[c]}' title='{k} {v:.0f}%'></i>"
                  for (k, v), c in zip(sh.items(), ("cpu", "hw", "bw"), strict=False)) + "</div>")
        sec = b.get("sections")
        if sec:
            h += "<div class='q4'>" + "".join(
                f"<div class='{cls}'><h4><i style='background:{col}'></i>{title}</h4><ul>"
                + "".join(f"<li>{_basis_tag(t)}{escape(o)}</li>" for o, t in sec.get(key) or []) + "</ul></div>"
                for key, cls, col, title in _Q4) + "</div>"
        else:
            bases = b.get("basis") or [""] * len(b["opinions"])
            h += "<ul>" + "".join(f"<li>{_basis_tag(t)}{escape(o)}</li>" for o, t in zip(b["opinions"], bases, strict=False)) + "</ul>"
        ev = b.get("evidence")
        if ev and not sec:
            h += (f"<p class=meta>근거: 실측 대조 variant {ev['measured_variants']}개"
                  + (f" · 보강 필요: {escape(', '.join(ev['needed']))}" if ev["needed"] else "") + "</p>")
        h += f"<details style='margin-top:6px'><summary class=meta>variant {len(b['variants'])}</summary><span class=meta>{escape(', '.join(_short(v) for v in b['variants']))}</span></details></div>"
    return h


_BASIS_CLS = {"실측": "b-meas", "산출": "b-calc", "가정": "b-asm", "입력": "b-in"}


def _basis_tag(t: str) -> str:
    if not t:
        return ""
    head = t.split(" ")[0]
    return f"<span class='bt {_BASIS_CLS.get(head, 'b-calc')}' title='{escape(t, quote=True)}'>{escape(head)}</span> "


def _latency(rows: list[dict[str, Any]]) -> str:
    h = ("<p class='meta'>Sensor frame 시작 → 출력 buffer 완료까지의 최대 지연과 연속 출력 간격 (조합 탐색의 목적 통계 slice, "
         "DVFS 상향 · compression 적용 전 timing). 간격이 목표 period ±0.1%를 벗어나면 fps 미달.</p>")
    rs = [r for r in rows if r.get("latency")]
    if not rs:
        return h + "<p class=meta>latency 정보 없음 (이전 형식 snapshot) — 재생성하면 표시</p>"
    h += ("<div class='scroll'><table><tr><th>Scenario</th><th>fps</th><th>period ms</th><th>Preview latency ms</th><th>(frame)</th>"
          "<th>Video latency ms</th><th>(frame)</th><th>Preview 간격 ms</th><th>Video 간격 ms</th><th>판정</th></tr>")
    for r in sorted(rs, key=lambda r: -(r["latency"].get("video_ms") or 0)):
        lat, iv, p = r["latency"], r.get("intervals") or {}, r.get("period_ms")

        def ivc(v: Any, p: Any = p) -> str:
            return "" if v is None or not p else ("fail" if abs(v - p) > p * 0.001 else "ok")
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'], 0)}</td><td class=n>{_f(p, 2)}</td>"
              f"<td class=n>{_f(lat.get('preview_ms'), 1)}</td><td class='n meta'>{_f(lat.get('preview_frames'), 2)}</td>"
              f"<td class=n>{_f(lat.get('video_ms'), 1)}</td><td class='n meta'>{_f(lat.get('video_frames'), 2)}</td>"
              f"<td class='n {ivc(iv.get('preview'))}'>{_f(iv.get('preview'), 2)}</td><td class='n {ivc(iv.get('video'))}'>{_f(iv.get('video'), 2)}</td>"
              f"<td class={'ok' if r['spec_ok'] else 'fail'}>{'OK' if r['spec_ok'] else 'FAIL'}</td></tr>")
    return h + "</table></div>"


def _scenarios(rows: list[dict[str, Any]]) -> str:
    h = ("<div class='scroll'><table><tr><th>Scenario</th><th>fps</th><th>EIS</th><th>판정</th><th>Total mW</th>"
         "<th>CPU</th><th>IP</th><th>IP BW</th><th>CPU BW</th><th>BW MB/s</th><th title='탐색 조합의 power 분포 (설계공간 범위) — 실측 신뢰구간이 아님'>설계공간 range mW</th><th>Compression</th><th>DVFS level</th><th>검증</th><th>출처</th></tr>")
    for r in rows:
        p, d = r["power"], r["distribution"]["total_mw"]
        ver = r.get("verified") or {}
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{'ON' if r['eis_on'] else '—'}</td>"
              f"<td class={'ok' if r['spec_ok'] else 'fail'}>{'OK' if r['spec_ok'] else 'FAIL'}"
              f"{_partial_tag(r)}</td>"
              f"<td class=n><b>{_f(p.get('total_mw'))}</b></td><td class=n>{_f(p.get('cpu_mw'))}</td><td class=n>{_f(p.get('hw_mw'))}</td>"
              f"<td class=n>{_f(p.get('bw_ip_mw', p.get('bw_mw')))}</td><td class=n>{_f(p.get('bw_cpu_mw'))}</td><td class=n>{_f(r['bw_mbs'],0)}</td><td class=n>{_f(d.get('min'),0)}–{_f(d.get('max'),0)}</td>"
              f"<td>{len(r['compression'])} buf{' <span class=warn>lossy</span>' if r.get('lossy') and r['compression'] else ''}</td>"
              f"<td>{escape(', '.join(f'{k}:L{v}' for k, v in sorted(r['dvfs'].items())))}</td>"
              f"<td title='{escape('; '.join(ver.get('reasons') or []), quote=True)}'>"
              f"{'✓ ' + _f(ver.get('delta_pct'), 2) + '%' if ver.get('ok') else ('✗' if ver else '—')}</td>"
              f"<td>{'등록 예측' if r.get('prediction_id') else '탐색 추천'}</td></tr>")
    return h + "</table></div>"


def _partial_tag(r: dict[str, Any]) -> str:
    """Power total over modeled IPs only: budget/total comparisons are lower bounds."""
    if r.get("power_coverage") not in ("partial", "none"):
        return ""
    ips = ", ".join(r.get("zero_power_ips") or [])
    return (f" <span class=warn title='{escape('전력 미모델 IP: ' + ips, quote=True)}'>부분 모델</span>")


def _clocks(clocks: list[dict[str, Any]]) -> str:
    nodes = sorted({c["node"] for c in clocks}, key=lambda n: (min(("rt", "nrt", "post", "output").index(c["stage"]) if c["stage"] in ("rt", "nrt", "post", "output") else 9 for c in clocks if c["node"] == n), n))
    variants = list(dict.fromkeys((c["scenario_id"], c["variant_id"]) for c in clocks))
    cell = {(c["scenario_id"], c["variant_id"], c["node"]): c for c in clocks}
    h = "<p class='meta'>셀 = 필요 → 설정 MHz · level · 전압. CAM 등 domain level은 scenario별로 다를 수 있음. 색 = headroom (진할수록 여유 적음)</p>"
    h += "<div class='scroll'><table><tr><th>Scenario</th>" + "".join(f"<th>{escape(n.upper())}</th>" for n in nodes) + "</tr>"
    for sid, v in variants:
        h += f"<tr><td title='{escape(sid, quote=True)}'>{escape(_short(v))}</td>"
        for n in nodes:
            c = cell.get((sid, v, n))
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
    variants = list(dict.fromkeys((r["scenario_id"], r["variant_id"]) for r in rows if r["spec_ok"]))
    cell = {(r["scenario_id"], r["variant_id"], r["domain"]): r for r in rows}
    h = ("<p class='meta'>DVFS domain별 선택 level (spec 만족 scenario). 셀 = level · MHz · mV / 필요 max MHz (driver IP). "
         "색이 진할수록 headroom 적음. CAM level은 scenario마다 다르게 설정 가능.</p>")
    h += "<div class='scroll'><table><tr><th>Scenario</th>" + "".join(f"<th>{escape(d)}</th>" for d in doms) + "</tr>"
    for sid, v in variants:
        h += f"<tr><td title='{escape(sid, quote=True)}'>{escape(_short(v))}</td>"
        for d in doms:
            c = cell.get((sid, v, d))
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
    h = f"<h3 style='margin:14px 0 4px'>spec 미달 {len(rows)}건 (margin 음수)</h3><table><tr><th>Scenario</th><th>fps</th><th>stage</th><th>SW / P</th><th>필요 단축</th><th>병목</th></tr>"
    for r in rows:
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{escape(r['stage'].upper())}</td>"
              f"<td class='n fail'>{_f(r['sw_share_pct'],0)}%</td><td class=n>{_f(-r['slack_ms'],2)} ms</td>"
              f"<td>{escape(str(r['bottleneck']))} {_f(r['bottleneck_ms'],1)} ms</td></tr>")
    return h + "</table>"


def _boxes(rows: list[dict[str, Any]]) -> str:
    rows = [r for r in rows if r["spec_ok"]]
    out = ("<p class='meta'>spec 만족 scenario만 표시 (미달은 ③). 중앙값 낮은 순 정렬 · 막대 = min–max, 상자 = p25–p75, 굵은 선 = median, "
           "◆ = 등록 예측 · 세로 점선 = power 100 mW / BW 1,000 MB/s 격자 (실선 = 눈금 표시)</p>"
           "<p class='meta'><b>해석</b>: 분포는 <b>설계공간 범위</b>(compression × DVFS × SW 통계·증가 조합)이며 실측 불확실성(신뢰구간)이 아님. "
           "추천 설정의 SW 증가 robustness는 SW margin 표의 ‘추천 DVFS 고정’ 열, 실측 불확실성은 반복 측정 CI(실측 대조)로 판단.</p>")
    for key, label, unit in (("total_mw", "Total power", "mW"), ("cpu_mw", "CPU (SW)", "mW"), ("hw_mw", "IP (HW core)", "mW"),
                             ("bw_ip_mw", "IP BW", "mW"), ("bw_cpu_mw", "CPU BW", "mW"),
                             ("bw_mbs", "BW", "MB/s")):
        out += f"<h3 style='margin:18px 0 6px'>{label} ({unit}) <span class=meta>— box = 조합 × SW 통계 · ◆ = 등록 예측</span></h3>" + _box_svg(rows, key)
    return out


_KEY_COLOR = {"total_mw": "total", "cpu_mw": "cpu", "hw_mw": "hw", "bw_mw": "bw", "bw_ip_mw": "bw", "bw_cpu_mw": "bwcpu", "bw_mbs": "bw"}


def _grid_step(hi: float, unit: str) -> tuple[float, int]:
    """(minor step, label every n minors): 100 mW grid for power, 1000 MB/s for BW; coarser when too dense."""
    base = (100.0 if hi >= 400 else 50.0 if hi >= 150 else 20.0) if unit == "mW" else 1000.0
    step = base
    while hi / step > 60:
        step *= 2.5 if str(step)[0] == "2" else 2
    every = 1
    while hi / (step * every) > 14:
        every = {1: 2, 2: 5, 5: 10}.get(every, every * 2)
    return step, every


def _box_svg(rows: list[dict[str, Any]], key: str) -> str:
    unit = "MB/s" if key == "bw_mbs" else "mW"
    lw, W, rh = 230, 1400, 24
    rows = [r for r in rows if r["distribution"].get(key)]
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["distribution"][key]["median"])
    hi = max(r["distribution"][key]["max"] for r in rows) * 1.04 or 1
    pw = W - lw - 190
    k = pw / hi
    H = len(rows) * rh + 30
    step, every = _grid_step(hi, unit)
    g = [f"<svg width='100%' viewBox='0 0 {W} {H}' style='max-width:{W}px;font-size:13px'>"]
    for i, _ in enumerate(rows):
        if i % 2:
            g.append(f"<rect x='0' y='{i * rh + 2}' width='{W}' height='{rh}' fill='#F8F6F2'/>")
    n = int(hi // step) + 1
    for t in range(n):
        x = lw + t * step * k
        major = t % every == 0
        dash = "" if major else " stroke-dasharray='2 3'"
        stroke = "#CFC7BA" if major else "#E2DCD2"
        g.append(f"<line x1='{x:.1f}' x2='{x:.1f}' y1='0' y2='{H-22}' stroke='{stroke}' stroke-width='{1.2 if major else 1}'{dash}/>")
        if major:
            g.append(f"<text x='{x:.1f}' y='{H-6}' font-size='12' fill='{C['mute']}' text-anchor='middle'>{t * step:,.0f}</text>")
    g.append(f"<text x='{lw + pw + 8}' y='{H-6}' font-size='12' fill='{C['mute']}'>{unit} · 격자 {step:,.0f}</text>")
    for i, r in enumerate(rows):
        d = r["distribution"][key]
        y = i * rh + 2
        cy = y + rh / 2
        g.append(f"<text x='{lw-8}' y='{cy + 4.5:.1f}' font-size='13' text-anchor='end' fill='{C['ink']}'>{escape(_short(r['variant_id']))}</text>")
        col = C[_KEY_COLOR[key]] if r["spec_ok"] else C["fail"]
        g.append(f"<g><title>{escape(_short(r['variant_id']))}: min {d['min']:,.0f} · p25 {d['p25']:,.0f} · median {d['median']:,.0f} · p75 {d['p75']:,.0f} · max {d['max']:,.0f} {unit}</title>")
        g.append(f"<line x1='{lw+d['min']*k:.1f}' x2='{lw+d['max']*k:.1f}' y1='{cy:.1f}' y2='{cy:.1f}' stroke='{col}' stroke-width='1.5'/>")
        g.append(f"<rect x='{lw+d['p25']*k:.1f}' y='{y+5}' width='{max(1.5,(d['p75']-d['p25'])*k):.1f}' height='{rh-10}' rx='2' fill='{col}' fill-opacity='.28' stroke='{col}'/>")
        g.append(f"<line x1='{lw+d['median']*k:.1f}' x2='{lw+d['median']*k:.1f}' y1='{y+4}' y2='{y+rh-4}' stroke='{col}' stroke-width='2.5'/></g>")
        mk = r["bw_mbs"] if key == "bw_mbs" else r["power"].get(key)
        if mk is not None:
            x = lw + mk * k
            g.append(f"<path d='M{x:.1f},{cy-7:.1f} l6,7 l-6,7 l-6,-7z' fill='#CC3311' stroke='#fff' stroke-width='.8'><title>등록 예측 {mk:,.0f} {unit}</title></path>")
        txt = (f"◆ {mk:,.0f} · " if mk is not None else "") + f"{d['min']:,.0f}–{d['max']:,.0f}"
        g.append(f"<text x='{lw + pw + 8}' y='{cy + 4.5:.1f}' font-size='12.5' fill='{C['ink']}'>{txt}</text>")
    g.append("</svg>")
    return "<div class='scroll'>" + "".join(g) + "</div>"


def _split(rows: list[dict[str, Any]]) -> str:
    lw, W, rh = 230, 1400, 22
    ok = [r for r in rows if r["power"].get("total_mw")]
    hi = max((r["power"]["total_mw"] for r in ok), default=1) * 1.05
    k = (W - lw - 120) / hi
    H = len(ok) * rh + 8
    g = [f"<div class='lg'><span><i style='background:{C['cpu']}'></i>CPU (SW)</span><span><i style='background:{C['bwcpu']}'></i>CPU BW</span>"
         f"<span><i style='background:{C['hw']}'></i>IP (HW core)</span><span><i style='background:{C['bw']}'></i>IP BW</span></div>",
         f"<div class='scroll'><svg width='100%' viewBox='0 0 {W} {H}' style='max-width:{W}px'>"]
    for i, r in enumerate(ok):
        p, y, x = r["power"], i * rh + 4, float(lw)
        g.append(f"<text x='{lw-8}' y='{y+13}' font-size='13' text-anchor='end'>{escape(_short(r['variant_id']))}</text>")
        parts = _parts(p)
        for key, val in parts:
            w = val * k
            g.append(f"<rect x='{x:.1f}' y='{y+1}' width='{max(0,w):.1f}' height='16' fill='{C[key]}'/>")
            x += w
        t = p["total_mw"]
        share = " · ".join(f"{lbl} {100*v/t:.0f}%" for lbl, v in zip(("CPU", "CPU BW", "IP", "IP BW"), [v for _, v in parts], strict=True))
        g.append(f"<text x='{x+6:.1f}' y='{y+13}' font-size='12.5' fill='{C['mute']}'>{t:,.0f} mW · {share}</text>")
    g.append("</svg></div>")
    return "".join(g)


def _parts(p: dict[str, Any]) -> list[tuple[str, float]]:
    """CPU, CPU BW, IP core, IP BW (engine rev 1 predictions: all BW as IP BW)."""
    bw_ip = p.get("bw_ip_mw", p.get("bw_mw")) or 0.0
    return [("cpu", p.get("cpu_mw") or 0.0), ("bwcpu", p.get("bw_cpu_mw") or 0.0),
            ("hw", p.get("hw_mw") or 0.0), ("bw", bw_ip)]


def _compression_only(buffers: list[dict[str, Any]], chosen: list[str]) -> dict[str, float]:
    sel = [b for b in buffers if b.get("buffer") in set(chosen) and "delta_mbs" in b]
    return {"compression_only_mbs": round(-sum(b["delta_mbs"] for b in sel), 2),
            "compression_only_mw": round(-sum(b.get("delta_mw", 0.0) for b in sel), 3)}


def _compression(rows: list[dict[str, Any]], scen: list[dict[str, Any]]) -> str:
    saved = [(r["variant_id"], (r["baseline_bw_mbs"] or 0) - (r["bw_mbs"] or 0), (r["baseline_total_mw"] or 0) - (r["power"].get("total_mw") or 0))
             for r in scen if r["spec_ok"] and r["baseline_bw_mbs"] is not None]
    only: list[tuple[float, float]] = [(float(r.get("compression_only_mbs") or 0.0), float(r["compression_only_mw"]))
                                       for r in scen if r["spec_ok"] and r.get("compression_only_mw") is not None]
    only_bw = sum(x[0] for x in only) / len(only) if only else None
    only_mw = sum(x[1] for x in only) / len(only) if only else None
    known = [c for c in rows if str(c.get("support") or "unknown") not in ("unknown", "None")]
    unknown = [c for c in rows if c not in known]

    def per_variant(cs: list[dict[str, Any]], key: str) -> float:
        n = sum(c["selected"] for c in cs)
        return sum(c[key] for c in cs) / n if n else 0.0
    avg_bw = sum(s[1] for s in saved) / len(saved) if saved else 0.0
    avg_mw = sum(s[2] for s in saved) / len(saved) if saved else 0.0
    h = ("<p class='meta'>등록 예측이 선택한 buffer 압축의 효과. 합산이 아닌 <b>variant 1개당 평균</b>으로 표시. "
         "IP 지원이 catalog로 확인되지 않은 buffer는 <span class=warn>잠재 절감</span>으로 분리 — HW 지원 확인 전에는 확정값이 아님.</p>"
         f"<div class='kpis'><div class='kpi' title='SW·DVFS 고정, 선택 buffer 압축만 적용한 효과 (buffer Δ 합, port 독립)'>압축 단독 BW 절감 (variant 평균)<b>{_f(only_bw, 0)}</b>MB/s</div>"
         f"<div class='kpi' title='SW·DVFS 고정, 선택 buffer 압축만 적용한 효과'>압축 단독 Power 절감 (variant 평균)<b>{_f(only_mw, 1)}</b>mW</div>"
         f"<div class='kpi' title='등록(추천) 조합 vs 무압축 · DVFS 기본 baseline — DVFS 변경 효과 포함'>조합 전체 절감 (vs baseline, 평균)<b>{avg_mw:,.1f}</b>mW · {avg_bw:,.0f} MB/s</div>"
         f"<div class='kpi'>IP 지원 확인 buffer<b class='ok'>{len(known)}</b>평균 {per_variant(known, 'selected_delta_mw'):+.1f} mW/적용</div>"
         f"<div class='kpi'>IP 지원 미확인 (잠재)<b class='warn'>{len(unknown)}</b>평균 {per_variant(unknown, 'selected_delta_mw'):+.1f} mW/적용</div></div>")
    h += ("<table style='margin-top:10px'><tr><th>Buffer</th><th>구분</th><th>Mode</th><th>ratio</th><th>ratio 출처</th><th>IP 지원</th><th>적용/대상</th>"
          "<th>ΔMB/s (적용 1건 평균)</th><th>ΔmW (적용 1건 평균)</th><th>ΔMB/s (전체 적용 시 1건 평균)</th></tr>")
    for c in known + unknown:
        sel = c["selected"] or 0

        def avg(k: str, n: int, c: dict[str, Any] = c) -> float | None:
            return c[k] / n if n else None
        h += (f"<tr><td>{escape(c['buffer'])}</td><td class={'ok' if c in known else 'warn'}>{'확정' if c in known else '잠재'}</td>"
              f"<td>{escape(str(c['mode']))}{' <span class=warn>lossy</span>' if c['lossy'] else ''}</td>"
              f"<td class=n>{_f(c['ratio'],2)}</td><td class={'warn' if c['ratio_source']=='assumed' else ''}>{escape(str(c['ratio_source']))}</td>"
              f"<td>{escape(str(c['support']))}</td><td class=n>{sel}/{c['variants']}</td>"
              f"<td class=n>{_f(avg('selected_delta_mbs', sel),0)}</td><td class=n>{_f(avg('selected_delta_mw', sel),1)}</td>"
              f"<td class=n>{_f(avg('delta_mbs', c['variants']),0)}</td></tr>")
    return h + "</table>"


def _lat_text(d: dict[str, Any] | None) -> str:
    if not d or all(v is None for v in d.values()):
        return "—"
    return " / ".join(f"{k[0].upper()} {v:+.1f}" for k, v in (("preview", d.get("preview_ms")), ("video", d.get("video_ms"))) if v is not None) + " ms"


def _iq_text(iq: str | None) -> str:
    return {"required": "<span class=warn>IQ 평가 필요</span>", "not_required": "<span class=ok>IQ 영향 없음(선언)</span>"}.get(str(iq), "—")


def _power_options(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p class='meta'>탐색된 power option 없음 (knobs.yaml explore / IP sim.modes substitutes 미선언)</p>"
    h = ("<p class='meta'>정식 variant가 아닌 power-saving 후보. 각 조합마다 compression·DVFS를 다시 탐색한 최소 전력을 "
         "variant 권장 case와 비교한다. PPA 3축 = Power(ΔmW) · Latency(Δ, P=preview / V=video) · 화질(IQ 평가 필요 여부). spec 미달 variant는 제외.</p>"
         "<table><tr><th>Scenario</th><th>fps</th><th>기준 mW</th><th>최대 절감 조합</th><th>ΔPower</th><th>ΔLatency</th><th>IQ</th><th>원인</th><th>단일 option (ΔmW · ΔLatency)</th></tr>")
    for r in rows:
        b = r["best"]
        cats = ", ".join(f"{k} {v:+.1f}" for k, v in list((b or {}).get("by_category", {}).items())[:3])
        singles = "<br>".join(f"{escape(x['label'])} <b class='n'>{x['delta_mw']:+.1f}</b> · {_lat_text(x.get('delta_latency_ms'))}"
                              f"{'' if x['spec_ok'] else ' <span class=fail>spec fail</span>'}" for x in r["singles"])
        delta = (f"<b>{b['delta_mw']:+.1f}</b> mW<br><span class=meta>{_f(b['delta_pct'], 1)}%</span>" if b else "—")
        best = escape(" + ".join(b["labels"])) if b else "—"
        h += (f"<tr><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td class=n>{_f(r['base_total_mw'],1)}</td>"
              f"<td>{best}</td><td class=n>{delta}</td><td class=n>{_lat_text((b or {}).get('delta_latency_ms'))}</td>"
              f"<td>{_iq_text((b or {}).get('iq_eval')) if b else '—'}</td><td>{escape(cats)}</td><td>{singles}</td></tr>")
    return h + "</table>"


def _margins(rows: list[dict[str, Any]]) -> str:
    h = ("<p class='meta'>SW timing margin = (P − SW(runtime+latency) − IP overhead − HW@set clock) / P, NRT·Post-NRT 중 최소, 목적 통계 기준</p>"
         "<table><tr><th>#</th><th>Scenario</th><th>fps</th><th>stage</th><th>margin</th><th>SW / P</th><th>병목 task</th><th title='DVFS를 growth마다 다시 고르면 허용되는 SW 증가 (재최적화 가능 범위)'>SW 증가 허용<br><span class=meta>DVFS 재선택</span></th>"
         "<th title='추천 DVFS level을 고정했을 때 흡수 가능한 SW 증가 (robustness)'>SW 증가 허용<br><span class=meta>추천 DVFS 고정</span></th><th>권고</th></tr>")
    for i, r in enumerate(rows, 1):
        h += (f"<tr><td>{i}</td><td>{escape(_short(r['variant_id']))}</td><td class=n>{_f(r['fps'],0)}</td><td>{escape(r['stage'].upper())}</td>"
              f"<td class='n {'fail' if r['margin_pct'] < 0 else ''}'><b>{_f(r['margin_pct'],1)}%</b><br><span class=meta>{_f(r['slack_ms'],2)} ms</span></td>"
              f"<td class=n>{_f(r['sw_share_pct'],0)}%</td><td>{escape(str(r['bottleneck']))} {_f(r['bottleneck_ms'],1)} ms ({_f(r['bottleneck_share_pct'],0)}%)</td>"
              f"<td class=n>{'×'+_f(r['growth_tolerance'],1) if r['growth_tolerance'] else '—'}</td>"
              f"<td class=n>{'×'+_f(r.get('growth_tolerance_fixed'),1) if r.get('growth_tolerance_fixed') else '—'}</td>"
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
