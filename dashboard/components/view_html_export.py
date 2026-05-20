"""Static HTML report export for ScenarioDB Pipeline Viewer views."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
import json
import re
from typing import Any, Literal

from dashboard.components.elk_viewer import build_elk_view_html
from dashboard.components.graph_inspector import (
    InspectorPanel,
    build_edge_inspector,
    build_graph_overview,
    build_node_inspector,
    edge_options,
    node_options,
)
from dashboard.components.level0_resource_overview import (
    buffer_handoff_rows,
    display_layer_rows,
    display_summary_rows,
    metric_breakdown_rows,
    resource_overview_rows,
    sensor_summary_rows,
)
from scenario_db.api.schemas.view import ViewResponse


ExportScope = Literal["scenario_pack", "full_drilldown"]
DEFAULT_EXPORT_SCOPE: ExportScope = "full_drilldown"


@dataclass(frozen=True)
class ExportDiagram:
    title: str
    view: ViewResponse
    canvas_height: int


@dataclass(frozen=True)
class ViewExportBundle:
    title: str
    resource_view: ViewResponse
    diagrams: list[ExportDiagram] = field(default_factory=list)
    inspector_views: list[ViewResponse] = field(default_factory=list)


@dataclass(frozen=True)
class ViewExportOptions:
    scope: ExportScope = DEFAULT_EXPORT_SCOPE
    include_raw_json: bool = False


def build_static_view_html(bundle: ViewExportBundle, options: ViewExportOptions | None = None) -> str:
    """Build a self-contained report shell that embeds each diagram as srcdoc HTML."""
    opts = options or ViewExportOptions()
    summary = bundle.resource_view.summary
    body = [
        _header_html(bundle, opts),
        _scenario_summary_html(bundle.resource_view),
        _level0_resource_html(bundle.resource_view),
        _diagram_sections_html(bundle.diagrams),
        _inspector_catalog_html(bundle.inspector_views),
    ]
    if opts.include_raw_json:
        body.append(_raw_json_html(bundle))
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<title>{escape(bundle.title)}</title>
<style>
  :root {{
    color-scheme: light;
    --bg: #F7F5F1;
    --panel: #FFFFFF;
    --line: #E5E7EB;
    --text: #111827;
    --muted: #64748B;
    --chip: #F8FAFC;
    --accent: #0F766E;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: Inter, Segoe UI, Arial, sans-serif; }}
  body {{ padding: 22px; }}
  .report {{ max-width: 1680px; margin: 0 auto; }}
  .hero, .section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; margin: 0 0 16px 0; }}
  .hero h1 {{ margin: 0 0 8px 0; font-size: 24px; letter-spacing: 0; }}
  .subtle {{ color: var(--muted); font-size: 12px; line-height: 1.45; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; }}
  .chip {{ display: inline-flex; border: 1px solid var(--line); border-radius: 7px; background: var(--chip); padding: 3px 8px; font-size: 11px; font-weight: 700; color: #475569; }}
  h2 {{ font-size: 17px; margin: 0 0 12px 0; }}
  h3 {{ font-size: 13px; margin: 16px 0 8px 0; color: #334155; }}
  table {{ width: 100%; border-collapse: collapse; margin: 8px 0 12px 0; font-size: 11px; }}
  th, td {{ border: 1px solid #E5E7EB; padding: 6px 7px; text-align: left; vertical-align: top; }}
  th {{ background: #F8FAFC; color: #475569; font-weight: 800; }}
  tr:nth-child(even) td {{ background: #FCFCFD; }}
  .diagram-frame {{ width: 100%; border: 0; display: block; background: #FFFFFF; }}
  .unavailable {{ border-left: 4px solid #F59E0B; background: #FFFBEB; border-radius: 8px; padding: 10px 12px; font-size: 12px; color: #713F12; }}
  details {{ border: 1px solid var(--line); border-radius: 8px; background: #FFFFFF; margin: 6px 0; padding: 8px 10px; }}
  summary {{ cursor: pointer; font-weight: 800; font-size: 12px; color: #334155; }}
  .note {{ border-left: 3px solid #CBD5E1; background: #F8FAFC; border-radius: 6px; padding: 6px 8px; margin: 4px 0; font-size: 11px; color: #374151; }}
  pre {{ white-space: pre-wrap; word-break: break-word; background: #0F172A; color: #E5E7EB; border-radius: 8px; padding: 12px; font-size: 11px; line-height: 1.45; }}
</style>
</head>
<body>
<main class="report">
{''.join(body)}
</main>
</body>
</html>"""


def export_filename(scenario_name: str, variant_id: str, scope: str) -> str:
    return f"scenario-view-{_slug(scenario_name)}-{_slug(variant_id)}-{_slug(scope)}.html"


def _header_html(bundle: ViewExportBundle, options: ViewExportOptions) -> str:
    summary = bundle.resource_view.summary
    diagram_count = len(bundle.diagrams)
    return f"""
<section class="hero">
  <h1>{escape(bundle.title)}</h1>
  <div class="subtle">Static ScenarioDB view export. Diagrams, resource tables, inspector summaries, and optional raw ViewResponse payloads are included in one file.</div>
  <div class="chips">
    <span class="chip">Scenario: {escape(summary.name)}</span>
    <span class="chip">ID: {escape(bundle.resource_view.scenario_id)}</span>
    <span class="chip">Variant: {escape(bundle.resource_view.variant_id)}</span>
    <span class="chip">Scope: {escape(options.scope)}</span>
    <span class="chip">Diagrams: {diagram_count}</span>
    <span class="chip">Resolution: {escape(summary.resolution)}</span>
    <span class="chip">FPS: {summary.fps:g}</span>
  </div>
</section>
"""


def _scenario_summary_html(view: ViewResponse) -> str:
    summary = view.summary
    rows = [
        {"Field": "Scenario", "Value": summary.name},
        {"Field": "Scenario ID", "Value": view.scenario_id},
        {"Field": "Variant", "Value": view.variant_id},
        {"Field": "Variant Label", "Value": summary.variant_label},
        {"Field": "Resolution", "Value": summary.resolution},
        {"Field": "Frame Rate", "Value": f"{summary.fps:g} fps"},
        {"Field": "Period", "Value": f"{summary.period_ms:g} ms"},
        {"Field": "Budget", "Value": f"{summary.budget_ms:g} ms"},
    ]
    if view.overlays_available:
        rows.append({"Field": "Overlays", "Value": ", ".join(view.overlays_available)})
    return f"""
<section class="section">
  <h2>Scenario Summary</h2>
  {_table_html(rows)}
</section>
"""


def _level0_resource_html(view: ViewResponse) -> str:
    if not view.level0_resource_overview:
        return ""
    parts = [
        "<section class=\"section\"><h2>Level 0 Resource Overview</h2>",
        _subtable_html("Scenario Resource Overview", resource_overview_rows(view)),
        _subtable_html("Subsystem Summary", metric_breakdown_rows(view)),
        _subtable_html("Buffer Handoffs", buffer_handoff_rows(view)),
        _subtable_html("Sensor Endpoints", sensor_summary_rows(view)),
        _subtable_html("Display Composition", display_summary_rows(view)),
        _subtable_html("Display Layers", display_layer_rows(view)),
        "</section>",
    ]
    return "".join(parts)


def _diagram_sections_html(diagrams: list[ExportDiagram]) -> str:
    parts: list[str] = []
    for diagram in diagrams:
        parts.append(f'<section class="section"><h2>{escape(diagram.title)}</h2>')
        if diagram.view.metadata.get("level2_available") is False:
            parts.append(_unavailable_html(diagram.view))
        else:
            srcdoc = escape(
                build_elk_view_html(diagram.view, canvas_height=diagram.canvas_height, title=diagram.title),
                quote=True,
            )
            parts.append(
                f'<iframe class="diagram-frame" title="{escape(diagram.title)}" '
                f'height="{diagram.canvas_height + 56}" srcdoc="{srcdoc}"></iframe>'
            )
        parts.append("</section>")
    return "".join(parts)


def _unavailable_html(view: ViewResponse) -> str:
    reasons = [str(item) for item in view.metadata.get("unavailable_reasons") or []]
    required = [str(item) for item in view.metadata.get("required_data") or []]
    reason_items = "".join(f"<li>{escape(item)}</li>" for item in reasons) or "<li>No reason was provided.</li>"
    required_items = "".join(f"<li>{escape(item)}</li>" for item in required)
    return f"""
<div class="unavailable">
  <b>Level 2 Module View Unavailable</b>
  <div>Expand target: {escape(str(view.metadata.get("expand") or ""))}</div>
  <ul>{reason_items}</ul>
  <div><b>Required fixture data</b></div>
  <ul>{required_items}</ul>
</div>
"""


def _inspector_catalog_html(views: list[ViewResponse]) -> str:
    if not views:
        return ""
    parts = ['<section class="section"><h2>Graph Inspector</h2>']
    for idx, view in enumerate(views, start=1):
        label = _view_label(view, idx)
        parts.append(f"<h3>{escape(label)}</h3>")
        parts.append(_panel_html(build_graph_overview(view)))
        node_items = node_options(view)
        if node_items:
            parts.append("<h3>Node Catalog</h3>")
            for option in node_items:
                parts.append(f"<details><summary>{escape(option.label)}</summary>")
                parts.append(_panel_html(build_node_inspector(view, option.id)))
                parts.append("</details>")
        edge_items = edge_options(view)
        if edge_items:
            parts.append("<h3>Edge Catalog</h3>")
            for option in edge_items:
                parts.append(f"<details><summary>{escape(option.label)}</summary>")
                parts.append(_panel_html(build_edge_inspector(view, option.id)))
                parts.append("</details>")
    parts.append("</section>")
    return "".join(parts)


def _panel_html(panel: InspectorPanel) -> str:
    sections = [f'<div class="subtle">{escape(panel.description)}</div>']
    for section in panel.sections:
        sections.append(f"<h3>{escape(section.title)}</h3>")
        if section.rows:
            sections.append(_table_html([{"Field": row.label, "Value": row.value} for row in section.rows]))
        for note in section.notes:
            sections.append(f'<div class="note">{escape(note)}</div>')
    return f"<div><h3>{escape(panel.title)}</h3>{''.join(sections)}</div>"


def _raw_json_html(bundle: ViewExportBundle) -> str:
    views = _unique_views([bundle.resource_view, *(diagram.view for diagram in bundle.diagrams), *bundle.inspector_views])
    payload = [
        {
            "level": view.level,
            "mode": view.mode,
            "scenario_id": view.scenario_id,
            "variant_id": view.variant_id,
            "view": view.model_dump(mode="json"),
        }
        for view in views
    ]
    return f"""
<section class="section">
  <h2>Raw ViewResponse JSON</h2>
  <details open><summary>ViewResponse payloads</summary><pre>{escape(json.dumps(payload, ensure_ascii=False, indent=2))}</pre></details>
</section>
"""


def _subtable_html(title: str, rows: list[dict[str, str]]) -> str:
    if not rows:
        return f"<h3>{escape(title)}</h3><div class=\"subtle\">No data provided.</div>"
    return f"<h3>{escape(title)}</h3>{_table_html(rows)}"


def _table_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body = []
    for row in rows:
        cells = "".join(f"<td>{escape(str(row.get(header, '')))}</td>" for header in headers)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _view_label(view: ViewResponse, index: int) -> str:
    expand = view.metadata.get("expand")
    suffix = f" / {expand}" if expand else ""
    return f"{index}. Level {view.level} {view.mode or ''}{suffix}".strip()


def _unique_views(views: list[ViewResponse]) -> list[ViewResponse]:
    unique: list[ViewResponse] = []
    seen: set[tuple[int, str | None, str | None]] = set()
    for view in views:
        key = (view.level, view.mode, str(view.metadata.get("expand") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(view)
    return unique


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "view"
