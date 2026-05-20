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
        _rows_table(_clock_rows(evidence)),
        "<h2>6. IP Details</h2>",
        _rows_table(ip_detail_rows(evidence)),
        "<h2>7. DMA Results</h2>",
        _rows_table(dma_report_rows(evidence)),
        "</body>",
        "</html>",
    ]
    return "\n".join(part for part in html if part)


def _clock_rows(evidence: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for row in ip_detail_rows(evidence):
        rows.append(
            {
                "Node": row.get("Node", "-"),
                "HW": row.get("HW", "-"),
                "DVFS": row.get("DVFS", "-"),
                "Req Freq": row.get("Req Freq", "-"),
                "Set Freq": row.get("Set Freq", "-"),
                "Set Volt": row.get("Set Volt", "-"),
                "HW Time(ms)": row.get("HW Time(ms)", "-"),
            }
        )
    return rows


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


def _rows_table(rows: list[dict[str, str]], *, total_marker: str | None = None) -> str:
    if not rows:
        return "<p class='empty'>No data available.</p>"
    columns = list(rows[0])
    header = "".join(f"<th>{escape(str(column))}</th>" for column in columns)
    body_rows = []
    for row in rows:
        cls = " class='total'" if total_marker and row.get(columns[0]) == total_marker else ""
        cells = "".join(f"<td>{escape(str(row.get(column, '-')))}</td>" for column in columns)
        body_rows.append(f"<tr{cls}>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


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
