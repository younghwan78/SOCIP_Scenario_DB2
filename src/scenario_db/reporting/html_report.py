from __future__ import annotations

from html import escape
from typing import Any

from scenario_db.reporting.models import ReportContext
from scenario_db.reporting.tables import (
    basic_conditions_rows,
    dma_report_rows,
    dvfs_guide_rows,
    ip_detail_rows,
    power_summary_rows,
    scenario_description_rows,
)


def generate_simulation_report_html(
    evidence: dict[str, Any],
    *,
    context: ReportContext,
    timing_chart_file: str | None = None,
    bw_chart_file: str | None = None,
) -> str:
    title = context.variant_name or context.variant_ref or context.evidence_id
    html = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{escape(title)} - Simulation Report</title>",
        "<style>",
        _css(),
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{escape(title)} - Simulation Report<span class='timestamp'>{escape(_timestamp(evidence))}</span></h1>",
        _chart_links(timing_chart_file=timing_chart_file, bw_chart_file=bw_chart_file),
        "<div class='two-col'>",
        "<div class='col'>",
        "<h2>1. Scenario Description</h2>",
        _kv_table(scenario_description_rows(evidence), class_name="info"),
        "</div>",
        "<div class='col'>",
        "<h2>2. Basic Conditions</h2>",
        _kv_table(basic_conditions_rows(evidence), class_name="info"),
        "</div>",
        "</div>",
        "<h2>3. DVFS Guide</h2>",
        _rows_table(dvfs_guide_rows(evidence)),
        "<h2>4. Power Results</h2>",
        _rows_table(power_summary_rows(evidence), total_marker="Total"),
        "<h2>5. Clock Results</h2>",
        _clock_results_html(evidence),
        "<h2>6. IP Details</h2>",
        _rows_table(ip_detail_rows(evidence)),
        "<h2>7. DMA Results</h2>",
        _rows_table(dma_report_rows(evidence)),
        "</body>",
        "</html>",
    ]
    return "\n".join(part for part in html if part)


def _clock_results_html(evidence: dict[str, Any]) -> str:
    rows = _clock_rows(evidence)
    if not rows:
        return "<p class='empty'>No data available.</p>"
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("_group") or "-"), []).append(row)
    sections = []
    for group, group_rows in groups.items():
        sections.append(_clock_group_title(group, group_rows))
        sections.append(_rows_table(group_rows))
    return "\n".join(sections)


def _clock_rows(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in _dict_rows(evidence.get("dvfs_breakdown")):
        required_voltage = _number(item.get("required_voltage_mv"))
        set_voltage = _number(item.get("set_voltage_mv"))
        delta_voltage = None if required_voltage is None or set_voltage is None else set_voltage - required_voltage
        driver = _is_vdd_driver(item)
        hw_name = _text(item.get("hw_name") or item.get("node_id"))
        display_name = f"{hw_name} *" if driver else hw_name
        rows.append(
            {
                "IP": display_name,
                "Mode": _text(item.get("mode")),
                "Req.Clk (MHz)": _fixed(item.get("required_clock_mhz"), 1),
                "Set.Clk (MHz)": _fixed(item.get("set_clock_mhz"), 1),
                "DVFS Lv": _text(item.get("dvfs_level")),
                "Req.Volt (mV)": _fixed(required_voltage, 2),
                "Set.Volt (mV)": _fixed(set_voltage, 2),
                "Delta Volt (mV)": _signed_fixed(delta_voltage, 2),
                "VDD": _text(item.get("vdd")),
                "ReqV Pwr (mW)": _fixed(_estimated_power_mw(item, required_voltage), 2),
                "SetV Pwr (mW)": _fixed(item.get("total_power_mw") or _estimated_power_mw(item, set_voltage), 2),
                "_group": _text(item.get("dvfs_group")),
                "_row_class": "vdd-driver" if driver else "",
                "_driver_vdd": _text(item.get("vdd")) if driver else "",
                "_driver_name": hw_name if driver else "",
                "_cell_classes": _clock_cell_classes(driver=driver, delta_voltage=delta_voltage),
            }
        )
    return rows


def _clock_group_title(group: str, rows: list[dict[str, Any]]) -> str:
    driver_vdds = sorted({str(row.get("_driver_vdd")) for row in rows if row.get("_driver_vdd")})
    driver_names = sorted({str(row.get("_driver_name")) for row in rows if row.get("_driver_name")})
    note = ""
    if driver_vdds and driver_names:
        note = (
            "<span class='group-note'>"
            f"VDD driver: {escape(', '.join(driver_names))} for {escape(', '.join(driver_vdds))}"
            "</span>"
        )
    return f"<h3 class='clock-group'>DVFS Group: {escape(group)}{note}</h3>"


def _timestamp(evidence: dict[str, Any]) -> str:
    run_info = evidence.get("run_info") if isinstance(evidence.get("run_info"), dict) else {}
    return str(run_info.get("timestamp") or "")


def _chart_links(*, timing_chart_file: str | None, bw_chart_file: str | None) -> str:
    links = []
    if timing_chart_file:
        links.append(f"<a href='{escape(timing_chart_file)}'>Timing Chart</a>")
    if bw_chart_file:
        links.append(f"<a href='{escape(bw_chart_file)}'>BW Chart</a>")
    if not links:
        return ""
    return "<div class='chart-links'>Charts: " + " | ".join(links) + "</div>"


def _kv_table(rows: dict[str, str], *, class_name: str = "") -> str:
    body = "\n".join(f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>" for key, value in rows.items())
    cls = f" class='{class_name}'" if class_name else ""
    return f"<table{cls}><tbody>{body}</tbody></table>"


def _rows_table(rows: list[dict[str, Any]], *, total_marker: str | None = None) -> str:
    if not rows:
        return "<p class='empty'>No data available.</p>"
    columns = [column for column in list(rows[0]) if not str(column).startswith("_")]
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body_rows = []
    for row in rows:
        row_classes = []
        if total_marker and row.get(columns[0]) == total_marker:
            row_classes.append("total")
        if row.get("_row_class"):
            row_classes.append(str(row["_row_class"]))
        cell_classes = row.get("_cell_classes") if isinstance(row.get("_cell_classes"), dict) else {}
        cells = "".join(
            f"<td{_class_attr(cell_classes.get(column))}>{escape(str(row.get(column, '-')))}</td>"
            for column in columns
        )
        body_rows.append(f"<tr{_class_attr(' '.join(row_classes))}>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _class_attr(value: Any) -> str:
    text = str(value or "").strip()
    return f" class='{escape(text)}'" if text else ""


def _clock_cell_classes(*, driver: bool, delta_voltage: float | None) -> dict[str, str]:
    classes = {}
    if driver:
        classes["IP"] = "vdd-driver-cell"
        classes["VDD"] = "vdd-driver-cell"
    if delta_voltage is not None and delta_voltage > 0:
        classes["Delta Volt (mV)"] = "voltage-delta-positive"
    return classes


def _is_vdd_driver(item: dict[str, Any]) -> bool:
    node_id = str(item.get("node_id") or "")
    leaders = {
        leader.strip()
        for leader in str(item.get("vdd_leader") or "").replace(";", ",").split(",")
        if leader.strip()
    }
    return bool(node_id and node_id in leaders)


def _estimated_power_mw(item: dict[str, Any], voltage_mv: float | None) -> float | None:
    unit_power = _number(item.get("unit_power_mw_mp"))
    resolution_mp = _number(item.get("input_resolution_mp"))
    fps = _number(item.get("fps"))
    if unit_power is None or resolution_mp is None or fps is None or voltage_mv is None:
        return None
    return unit_power * resolution_mp * (voltage_mv / 710.0) ** 2 * (fps / 30.0)


def _fixed(value: Any, digits: int) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.{digits}f}"


def _signed_fixed(value: Any, digits: int) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:+.{digits}f}"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return "-" if value is None or value == "" else str(value)


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _css() -> str:
    return """
body {
  font-family: 'Segoe UI', Arial, sans-serif;
  max-width: 1400px;
  margin: 32px auto;
  padding: 0 24px;
  background: #F8FAFC;
  color: #111827;
}
h1 {
  color: #174D47;
  font-size: 1.6em;
  font-weight: 700;
  border-bottom: 2px solid #CBD5E1;
  padding-bottom: 10px;
}
h2 {
  color: #2F6F68;
  margin-top: 28px;
  font-size: 1.15em;
  border-left: 4px solid #75B2A8;
  padding-left: 10px;
}
h3.clock-group {
  color: #334155;
  margin: 16px 0 8px;
  font-size: 0.98em;
  border-left: 3px solid #BFDBFE;
  padding-left: 10px;
}
.group-note {
  color: #DC2626;
  font-size: 0.85em;
  font-weight: 700;
  margin-left: 12px;
}
.two-col { display: flex; gap: 24px; flex-wrap: wrap; }
.two-col .col { flex: 1; min-width: 300px; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0 20px;
  background: #FFFFFF;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(16,24,40,0.08);
  font-size: 0.85em;
  overflow: hidden;
}
th {
  background: #E8F1EF;
  color: #174D47;
  padding: 8px 10px;
  font-weight: 700;
  text-align: center;
  white-space: nowrap;
}
td {
  padding: 6px 10px;
  border-bottom: 1px solid #F1F5F9;
  text-align: center;
  white-space: nowrap;
}
table.info th { text-align: left; min-width: 140px; background: #EEF2F7; color: #334155; }
table.info td { text-align: left; }
tr:nth-child(even) { background: #F8FAFC; }
tr.total { background: #E8F1EF; font-weight: 700; }
tr.vdd-driver td { font-weight: 700; }
td.vdd-driver-cell,
td.voltage-delta-positive {
  color: #DC2626;
  font-weight: 700;
}
td.feature-highlight {
  color: #DC2626;
  background: #FEF3C7;
  font-weight: 700;
}
.timestamp {
  float: right;
  font-size: 0.55em;
  font-weight: 400;
  color: #475569;
  background: #E2E8F0;
  padding: 4px 12px;
  border-radius: 8px;
}
.chart-links {
  margin: 12px 0 16px;
  padding: 8px 14px;
  background: #E8F1EF;
  border: 1px solid #B9D2CC;
  border-radius: 8px;
  font-size: 0.9em;
}
.chart-links a { color: #174D47; text-decoration: none; font-weight: 700; margin: 0 4px; }
.empty { color: #667085; }
"""
