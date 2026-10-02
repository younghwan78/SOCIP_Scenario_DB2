"""Architecture report snapshot → .xlsx (R14), with no extra dependency.

Writes a minimal SpreadsheetML package (inline strings, numbers as numbers, frozen header row)
so the frozen report numbers can be filtered and charted in Excel. One sheet per report table.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape, quoteattr

Row = list[Any]
Sheet = tuple[str, Row, list[Row]]  # name, header, rows

_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v: Any, style: int = 0) -> str:
    st = f' s="{style}"' if style else ""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"{st}><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    text = escape(_BAD.sub("", str(v)))
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(header: Row, rows: list[Row]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
           "<cols>" + "".join(f'<col min="{i + 1}" max="{i + 1}" width="{min(60, max(10, len(str(h)) + 4))}" customWidth="1"/>'
                               for i, h in enumerate(header)) + "</cols>", "<sheetData>"]
    for r, row in enumerate([header, *rows], 1):
        style = 1 if r == 1 else 0
        out.append(f'<row r="{r}">' + "".join(_cell(f"{_col(c)}{r}", v, style) for c, v in enumerate(row)) + "</row>")
    out.append("</sheetData>")
    if rows:
        out.append(f'<autoFilter ref="A1:{_col(len(header) - 1)}{len(rows) + 1}"/>')
    out.append("</worksheet>")
    return "".join(out)


def write_xlsx(sheets: list[Sheet]) -> bytes:
    names = []
    used: set[str] = set()
    for name, _, _ in sheets:
        base = re.sub(r"[\[\]:*?/\\]", "_", _BAD.sub("", name)).strip("'")[:31] or "Sheet"
        n = base
        suffix = 1
        while n.casefold() in used:
            tail = f"_{suffix}"
            n = base[:31 - len(tail)] + tail
            suffix += 1
        names.append(n)
        used.add(n.casefold())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(1, len(sheets) + 1)) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name={quoteattr(n)} sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                             for i in range(1, len(sheets) + 1))
                   + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="10"/><name val="Malgun Gothic"/></font><font><b/><sz val="10"/><name val="Malgun Gothic"/></font></fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFF3EFE8"/></patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i, (_, header, rows) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(header, rows))
    return buf.getvalue()


def _r(v: Any, d: int = 1) -> Any:
    return round(v, d) if isinstance(v, float) else v


def report_sheets(snap: dict[str, Any], meta: dict[str, Any] | None = None) -> list[Sheet]:
    """Report snapshot tables as sheets (numbers stay numbers)."""
    o, s = snap["overview"], snap["spec_summary"]
    c = snap.get("conclusion") or {}
    info: list[Row] = [["보고서", (meta or {}).get("title")], ["보고서 id", (meta or {}).get("id")], ["상태", (meta or {}).get("status")],
                       ["Target SoC", o.get("target_soc")], ["Project", o.get("project")], ["Scenario type", o.get("scenario_type")],
                       ["Exploration run", o.get("run_id")], ["DVFS table", o.get("dvfs_table_ref")], ["DVFS SAMPLE", o.get("sample_dvfs")],
                       ["Engine", o.get("engine_rev")], ["결론", c.get("headline")],
                       ["신뢰도", (c.get("confidence") or {}).get("grade")], ["신뢰도 의미", (c.get("confidence") or {}).get("meaning")]]
    info += [["신뢰도 근거", r] for r in (c.get("confidence") or {}).get("reasons", [])]
    info += [[f"리스크 {i}", f"{r['title']} — {r['detail']}"] for i, r in enumerate(c.get("risks") or [], 1)]
    info += [["모델 한계", x] for x in o.get("model_limits") or []]
    sheets: list[Sheet] = [("요약", ["항목", "값"], info)]
    sheets.append(("권고 조치", ["조치", "대상", "ΔPower mW", "Δ%", "근거", "필요 검증"],
                   [[a["action"], a["target"], _r(a.get("delta_mw")), _r(a.get("delta_pct"), 2), a["basis"], a["check"]] for a in c.get("actions") or []]))
    sheets.append(("Scenario", ["scenario", "variant", "fps", "EIS", "spec", "total mW", "CPU mW", "IP mW", "IP BW mW", "CPU BW mW", "BW MB/s",
                                "range min mW", "range max mW", "compression buf", "DVFS", "prediction id"],
                   [[r["scenario_id"], r["variant_id"], r["fps"], r["eis_on"], "OK" if r["spec_ok"] else "FAIL",
                     _r(r["power"].get("total_mw")), _r(r["power"].get("cpu_mw")), _r(r["power"].get("hw_mw")),
                     _r(r["power"].get("bw_ip_mw", r["power"].get("bw_mw"))), _r(r["power"].get("bw_cpu_mw")), _r(r.get("bw_mbs"), 0),
                     _r((r.get("distribution") or {}).get("total_mw", {}).get("min")), _r((r.get("distribution") or {}).get("total_mw", {}).get("max")),
                     len(r.get("compression") or []), ", ".join(f"{k}:L{v}" for k, v in sorted((r.get("dvfs") or {}).items())), r.get("prediction_id")]
                    for r in snap["scenarios"]]))
    sheets.append(("Spec 미달", ["variant", "원인", "필요 조치", "원문"],
                   [[f["variant_id"], e["text"], e["action"], e["raw"]] for f in s["failed"] for e in (f.get("explained") or
                    [{"text": x, "action": "", "raw": x} for x in f["reasons"]])]))
    sheets.append(("Latency", ["variant", "fps", "period ms", "preview latency ms", "video latency ms", "preview interval ms", "video interval ms", "spec"],
                   [[r["variant_id"], r["fps"], _r(r.get("period_ms"), 3), _r((r.get("latency") or {}).get("preview_ms")), _r((r.get("latency") or {}).get("video_ms")),
                     _r((r.get("intervals") or {}).get("preview"), 3), _r((r.get("intervals") or {}).get("video"), 3), "OK" if r["spec_ok"] else "FAIL"]
                    for r in snap["scenarios"] if r.get("latency")]))
    sheets.append(("실측 대조", ["variant", "합성", "측정일", "실측 mW", "예측 mW", "total Δ%", "CPU Δ%", "IP Δ%", "BW Δ%", "미모델 mW", "최대 오차 항목", "상쇄"],
                   [[r["variant_id"], r["synthetic"], str(r.get("measured_at") or "")[:10], _r(r["measured_mw"]), _r(r["predicted_mw"]), _r(r["delta_pct"], 2)]
                    + [_r(next((x["delta_pct"] for x in r["rows"] if x["category"] == k), None), 2) for k in ("cpu", "ip", "bw")]
                    + [_r(r.get("unmodeled_mw")), r["fit"]["worst_category"], r["fit"]["offsetting"]] for r in snap.get("calibration") or []]))
    sheets.append(("Compression", ["scenario", "buffer", "mode", "ratio", "ratio 출처", "IP 지원", "적용", "대상", "Δ MB/s (적용 합)", "Δ mW (적용 합)", "Δ MB/s (전체 적용)"],
                   [[x["scenario_id"], x["buffer"], x["mode"], x["ratio"], x["ratio_source"], x["support"], x["selected"], x["variants"],
                     x["selected_delta_mbs"], x["selected_delta_mw"], x["delta_mbs"]] for x in snap.get("compression") or []]))
    po_rows: list[Row] = []
    for p in snap.get("power_options") or []:
        for x in p["singles"]:
            lat = x.get("delta_latency_ms") or {}
            po_rows.append([p["variant_id"], p["fps"], _r(p.get("base_total_mw")), x["label"], x.get("kind"), _r(x["delta_mw"]), _r(x["delta_pct"], 2),
                            lat.get("preview_ms"), lat.get("video_ms"), x.get("iq_eval"), x["spec_ok"]])
    sheets.append(("Power option", ["variant", "fps", "기준 mW", "option", "종류", "ΔmW", "Δ%", "Δ preview latency ms", "Δ video latency ms", "IQ", "spec"], po_rows))
    sheets.append(("IP clock", ["scenario", "variant", "node", "stage", "DVFS group", "required MHz", "set MHz", "level", "mV", "headroom %"],
                   [[x["scenario_id"], x["variant_id"], x["node"], x["stage"], x["dvfs_group"], _r(x.get("required_mhz")), x.get("set_mhz"), x.get("level"),
                     x.get("voltage_mv"), x.get("headroom_pct")] for x in snap.get("clocks") or []]))
    return sheets
