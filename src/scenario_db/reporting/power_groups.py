"""Power by component — which scenarios lead CPU, BW and each IP group (ISP · Codec · DPU · GPU · NPU).

A spec-stage review asks two questions of power: which scenarios cost the most overall, and which ones lead each
component, since each component has its own owner and its own levers. Per-IP power is frozen in each report row
(``ip_mw`` by pipeline node, ``assumed_mw`` for declared assumed loads such as GPU / NPU); grouping happens at render
time with the frozen policy, so a project can map its own node names through ``review_policy.ip_groups``.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from html import escape
from typing import Any

IP_GROUPS = ("ISP", "Codec", "DPU", "GPU", "NPU")
OTHER = "기타 IP"
# component columns in display order: CPU (SW), BW (IP + CPU traffic incl. DRAM), then the IP groups
COMPONENTS = ("CPU", "BW", *IP_GROUPS, OTHER)

# built-in node-name rules (after a front_ / rear_ / sub_ prefix); a project's review_policy.ip_groups wins
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Codec", ("mfc*", "apv*", "codec*", "jpeg*", "*_enc", "*_dec", "venc*", "vdec*")),
    ("DPU", ("dpu*", "dpp*", "decon*", "disp*")),
    ("GPU", ("gpu*", "g3d*", "mali*")),
    ("NPU", ("npu*", "dnc*", "dsp*")),
    ("ISP", ("csis*", "pdp*", "byrp*", "rgbp*", "mcsc*", "mtnr*", "msnr*", "mlsc*", "yuvp*", "yuvsc*", "lme*", "gdc*",
             "vps*", "isp*", "3aa*", "mcfp*", "dns*", "tnr*", "drc*", "ipp*", "orb*", "cstat*", "lhfd*")),
)
_PREFIXES = ("front_", "rear_", "sub_", "tele_", "uw_")


def group_of(node: str, overrides: dict[str, str] | None = None) -> str:
    """Report group of an IP node (or of an assumed load's ip key): policy globs first, then the built-in rules."""
    name = str(node).lower()
    for pattern, group in (overrides or {}).items():
        if fnmatchcase(name, str(pattern).lower()):
            return group
    base = next((name[len(p):] for p in _PREFIXES if name.startswith(p)), name)
    for group, patterns in _RULES:
        if any(fnmatchcase(base, p) for p in patterns):
            return group
    return OTHER


def components(row: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, float | None]:
    """mW per component of one report row; IP groups with no node and no assumed load are ``None`` (미입력)."""
    p = row.get("power") or {}
    out: dict[str, float | None] = {"CPU": p.get("cpu_mw"), "BW": p.get("bw_mw")}
    groups: dict[str, float] = {}
    for node, mw in (row.get("ip_mw") or {}).items():
        g = group_of(node, overrides)
        groups[g] = groups.get(g, 0.0) + float(mw or 0.0)
    for ip, mw in (row.get("assumed_mw") or {}).items():
        g = group_of(ip, overrides)
        groups[g] = groups.get(g, 0.0) + float(mw or 0.0)
    for g in (*IP_GROUPS, OTHER):
        out[g] = round(groups[g], 3) if g in groups else None
    return out


def _rows(snap: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in snap.get("scenarios") or [] if r.get("spec_ok") and (r.get("power") or {}).get("total_mw") is not None]


def component_table(snap: dict[str, Any]) -> dict[str, Any]:
    """Frozen-snapshot view: per row the component mW, per component the ranking and whether any input exists."""
    overrides = (((snap.get("review_context") or {}).get("policy") or {}).get("ip_groups")) or {}
    rows = _rows(snap)
    table = []
    for r in rows:
        c = components(r, overrides)
        table.append({"scenario_id": r["scenario_id"], "variant_id": r["variant_id"],
                      "total_mw": float(r["power"]["total_mw"]), "parts": c,
                      "assumed": sorted({group_of(ip, overrides) for ip in (r.get("assumed_mw") or {})})})
    present = {k: any(t["parts"][k] is not None for t in table) for k in COMPONENTS}
    rank: dict[str, dict[tuple[str, str], int]] = {}
    for k in ("total", *COMPONENTS):
        vals = [(t["total_mw"] if k == "total" else t["parts"][k], (t["scenario_id"], t["variant_id"])) for t in table]
        ordered = sorted((v for v in vals if v[0] is not None and v[0] > 0), key=lambda x: -float(x[0] or 0.0))
        rank[k] = {key: i for i, (_, key) in enumerate(ordered, 1)}
    # IP nodes that fell into 기타 IP (so the mapping can be fixed through review_policy.ip_groups)
    other_nodes = sorted({n for r in rows for n in (r.get("ip_mw") or {}) if group_of(n, overrides) == OTHER})
    return {"rows": table, "present": present, "rank": rank, "other_nodes": other_nodes,
            "legacy": bool(rows) and not any("ip_mw" in r for r in rows)}


def _short(v: str) -> str:
    return v.replace("cam-rec-", "")


def ranking_block(snap: dict[str, Any], n: int = 5) -> str:
    """Top-n scenarios per component, side by side: which scenario leads CPU, BW and each IP group."""
    ct = component_table(snap)
    if not ct["rows"]:
        return ""
    if ct["legacy"]:
        return ("<h3 style='margin:12px 0 4px'>요소별 순위</h3><p class=meta>이 snapshot에는 IP별 power가 없음 — "
                "보고서를 재생성하면 IP 군(ISP · Codec · DPU · GPU · NPU)별 순위가 표시됩니다.</p>")
    by = {(t["scenario_id"], t["variant_id"]): t for t in ct["rows"]}
    cols = ["total", *(k for k in COMPONENTS if ct["present"][k] and k != OTHER)]
    if ct["present"][OTHER]:
        cols.append(OTHER)
    missing = [k for k in IP_GROUPS if not ct["present"][k]]

    def cell(k: str, i: int) -> str:
        key = next((key for key, rk in ct["rank"][k].items() if rk == i), None)
        if key is None:
            return "<td></td>"
        t = by[key]
        mw = t["total_mw"] if k == "total" else t["parts"][k]
        share = "" if k == "total" or not t["total_mw"] else f" <span class=meta>{100 * float(mw or 0) / t['total_mw']:.0f}%</span>"
        return f"<td><b>{escape(_short(t['variant_id']))}</b><div class=n>{float(mw or 0):,.0f} mW{share}</div></td>"

    label = {"total": "Total"}
    h = (f"<h3 style='margin:12px 0 4px'>요소별 순위 — 상위 {n} (spec 만족 · 등록 예측)</h3>"
         "<p class=meta>요소마다 owner와 절감 lever가 달라 요소별 상위 scenario를 따로 본다. % = 그 scenario total 중 비중. "
         "BW = IP + CPU traffic (MIF · DRAM 포함)."
         + (f" <b>미입력: {escape(' · '.join(missing))}</b> — pipeline node 또는 가정 부하(design_conditions "
            "<span class=mono>assumed_&lt;ip&gt;_mw</span>)가 없어 순위에서 빠짐 (0 mW가 아님)." if missing else "")
         + "</p><table><tr><th>#</th>" + "".join(f"<th>{escape(label.get(k, k))}</th>" for k in cols) + "</tr>")
    for i in range(1, n + 1):
        h += f"<tr><td class=n>{i}</td>" + "".join(cell(k, i) for k in cols) + "</tr>"
    h += "</table>"
    if ct["other_nodes"]:
        h += (f"<p class=meta>기타 IP로 분류된 node: <span class=mono>{escape(', '.join(ct['other_nodes'][:12]))}</span>"
              + (f" 외 {len(ct['other_nodes']) - 12}" if len(ct["other_nodes"]) > 12 else "")
              + " — review_policy.ip_groups로 군 지정 가능</p>")
    return h


def heatmap_block(snap: dict[str, Any], top: int = 15) -> str:
    """Scenario × component mW, shaded within each column; the top 3 of a column are bold."""
    ct = component_table(snap)
    if not ct["rows"] or ct["legacy"]:
        return ""
    cols = [k for k in COMPONENTS if ct["present"][k]]
    mx = {k: max((float(t["parts"][k] or 0) for t in ct["rows"]), default=0.0) or 1.0 for k in cols}
    rows = sorted(ct["rows"], key=lambda t: -t["total_mw"])

    def table(rs: list[dict[str, Any]]) -> str:
        h = "<table class='hm'><tr><th>Variant</th><th>Total mW</th>" + "".join(f"<th>{escape(k)}</th>" for k in cols) + "</tr>"
        for t in rs:
            key = (t["scenario_id"], t["variant_id"])
            h += f"<tr><td>{escape(_short(t['variant_id']))}</td><td class=n><b>{t['total_mw']:,.0f}</b></td>"
            for k in cols:
                v = t["parts"][k]
                if v is None:
                    h += "<td class=meta>—</td>"
                    continue
                a = min(1.0, float(v) / mx[k])
                rk = ct["rank"][k].get(key)
                tag = " · 가정 부하 포함" if k in t["assumed"] else ""
                h += (f"<td class=n style='background:rgba(180,83,9,{0.08 + 0.42 * a:.2f})' title='{escape(k)} 순위 {rk or '—'}{tag}'>"
                      + (f"<b>{float(v):,.0f}</b>" if rk and rk <= 3 else f"{float(v):,.0f}") + "</td>")
            h += "</tr>"
        return h + "</table>"

    out = (f"<h3 style='margin:12px 0 4px'>Scenario × 요소 power (mW) — Total 상위 {min(top, len(rows))}</h3>"
           "<p class=meta>열마다 최대값 대비 음영 · 굵게 = 그 요소 상위 3. — = 입력 없음 · 0 = node는 있으나 power model 0 mW. "
           "가정 부하가 들어간 셀은 title에 “가정 부하 포함”.</p>"
           + table(rows[:top]))
    if len(rows) > top:
        out += f"<details class='more'><summary>전체 {len(rows)} variant ▸</summary>{table(rows)}</details>"
    return out
