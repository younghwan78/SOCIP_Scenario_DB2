r"""DB Explorer for ScenarioDB.

Run:
  .\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py
"""
from __future__ import annotations

import os
import sys
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.explorer_api_client import (  # noqa: E402
    ViewerApiError,
    get_import_health,
    get_scenario_catalog,
    get_summary,
    get_variant_matrix,
    viewer_link,
)
from dashboard.components.viewer_api_client import (  # noqa: E402
    list_projects,
    list_soc_platforms,
    project_label,
    soc_label,
)


st.set_page_config(
    page_title="DB Explorer - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  .block-container {
    padding-top: 0.6rem !important;
    padding-left: 1.2rem !important;
    padding-right: 1.2rem !important;
    max-width: none !important;
  }
  header[data-testid="stHeader"], footer, #MainMenu { display: none !important; }
  section[data-testid="stSidebar"] { width: 275px !important; min-width: 275px !important; }
  section[data-testid="stSidebar"] > div { width: 275px !important; }
  .explorer-header {
    display: flex;
    align-items: center;
    gap: 10px;
    border-bottom: 1px solid #E8E4DF;
    padding: 4px 0 12px 0;
    margin-bottom: 12px;
  }
  .explorer-title {
    font-size: 24px;
    font-weight: 850;
    color: #111827;
  }
  .meta-chip {
    display: inline-block;
    background: #F3F4F6;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 11px;
    color: #4B5563;
    font-weight: 700;
    margin-right: 5px;
  }
  .metric-card {
    border: 1px solid #E8E4DF;
    border-radius: 13px;
    background: linear-gradient(180deg, #FFFFFF 0%, #FAF9F7 100%);
    padding: 13px 14px;
  }
  .metric-label {
    color: #6B7280;
    font-size: 11px;
    font-weight: 750;
    letter-spacing: .05em;
    text-transform: uppercase;
  }
  .metric-value {
    color: #111827;
    font-size: 28px;
    line-height: 1.15;
    font-weight: 850;
    margin-top: 5px;
  }
  .help-card {
    border: 1px solid #E5E7EB;
    border-radius: 13px;
    background: #FFFFFF;
    padding: 12px 14px;
    color: #374151;
    font-size: 13px;
    line-height: 1.5;
    margin-bottom: 12px;
  }
  .help-card b { color: #111827; }
  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 7px;
    margin: 6px 0 12px 0;
  }
  .tag-chip {
    display: inline-flex;
    align-items: center;
    border-radius: 999px;
    border: 1px solid var(--chip-border);
    background: var(--chip-bg);
    color: var(--chip-fg);
    font-size: 11px;
    line-height: 1;
    font-weight: 800;
    padding: 5px 8px;
    margin: 2px 3px 2px 0;
    white-space: nowrap;
  }
  .tag-chip.domain { border-style: dashed; }
  .catalog-card {
    border: 1px solid #E8E4DF;
    border-radius: 13px;
    background: #FFFFFF;
    padding: 12px 14px;
    margin-bottom: 10px;
  }
  .catalog-card-title {
    font-weight: 850;
    color: #111827;
    margin-bottom: 4px;
  }
  .catalog-card-meta {
    color: #6B7280;
    font-size: 12px;
    margin-bottom: 6px;
  }
  .catalog-card-kv {
    color: #374151;
    font-size: 12px;
    margin-top: 6px;
  }
  .health-error { color: #B91C1C; font-weight: 800; }
  .health-warning { color: #92400E; font-weight: 800; }
  .health-info { color: #1D4ED8; font-weight: 800; }
</style>
""",
    unsafe_allow_html=True,
)


_CATEGORY_PALETTE = {
    "camera": ("#FFF7ED", "#FDBA74", "#9A3412"),
    "display": ("#EFF6FF", "#93C5FD", "#1D4ED8"),
    "video": ("#F5F3FF", "#C4B5FD", "#5B21B6"),
    "codec": ("#FAF5FF", "#D8B4FE", "#7E22CE"),
    "audio": ("#ECFDF5", "#86EFAC", "#166534"),
    "game": ("#FFF1F2", "#FDA4AF", "#BE123C"),
    "call": ("#F0FDFA", "#5EEAD4", "#0F766E"),
    "youtube": ("#FEF2F2", "#FCA5A5", "#B91C1C"),
    "gallery": ("#FDF4FF", "#F0ABFC", "#A21CAF"),
}

_DOMAIN_PALETTE = {
    "camera": ("#F0FDFA", "#99F6E4", "#115E59"),
    "display": ("#EEF2FF", "#A5B4FC", "#3730A3"),
    "video": ("#F5F3FF", "#DDD6FE", "#6D28D9"),
    "codec": ("#FDF2F8", "#F9A8D4", "#BE185D"),
    "audio": ("#F0FDF4", "#BBF7D0", "#15803D"),
    "cpu": ("#F9FAFB", "#D1D5DB", "#374151"),
    "gpu": ("#FFF7ED", "#FED7AA", "#C2410C"),
    "npu": ("#ECFEFF", "#67E8F9", "#0E7490"),
}


@st.cache_data(ttl=30)
def _load_soc_options(api_base: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_soc_platforms(api_base), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_project_options(api_base: str, soc_ref: str | None, board_type: str | None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_projects(api_base, soc_ref=soc_ref, board_type=board_type), None
    except ViewerApiError as exc:
        return [], str(exc)


@st.cache_data(ttl=30)
def _load_explorer(api_base: str, filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str | None]:
    try:
        summary = get_summary(api_base, **filters)
        catalog = get_scenario_catalog(api_base, **{**filters, "limit": 5000})
        matrix = get_variant_matrix(api_base, **{**filters, "limit": 10000})
        health = get_import_health(api_base, **filters)
        return summary, catalog, matrix, health, None
    except ViewerApiError as exc:
        return {}, {}, {}, {}, str(exc)


def _palette_for(label: str, kind: str = "category") -> tuple[str, str, str]:
    key = str(label).strip().lower()
    palette = _DOMAIN_PALETTE if kind == "domain" else _CATEGORY_PALETTE
    if key in palette:
        return palette[key]
    fallback = [
        ("#F8FAFC", "#CBD5E1", "#334155"),
        ("#F0F9FF", "#BAE6FD", "#0369A1"),
        ("#FEFCE8", "#FDE68A", "#A16207"),
        ("#F7FEE7", "#BEF264", "#4D7C0F"),
        ("#FDF2F8", "#FBCFE8", "#BE185D"),
    ]
    return fallback[sum(ord(char) for char in key) % len(fallback)]


def _tag_chip(label: Any, kind: str = "category", count: int | None = None) -> str:
    text = str(label)
    bg, border, fg = _palette_for(text, kind)
    suffix = f" {count}" if count is not None else ""
    css_class = "tag-chip domain" if kind == "domain" else "tag-chip"
    return (
        f'<span class="{css_class}" style="--chip-bg:{bg};--chip-border:{border};'
        f'--chip-fg:{fg};">{escape(text)}{suffix}</span>'
    )


def _tag_chips(labels: list[Any], kind: str = "category") -> str:
    unique_labels = _unique_labels(labels)
    if not unique_labels:
        return _tag_chip("uncategorized", kind)
    return "".join(_tag_chip(label, kind) for label in unique_labels)


def _unique_labels(labels: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        text = str(label)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _rows_with_viewer_link(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        row = dict(item)
        row["open_viewer"] = viewer_link(item.get("viewer_query") or {})
        row.pop("viewer_query", None)
        rows.append(row)
    return rows


def _catalog_table_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in _rows_with_viewer_link(items):
        rows.append(
            {
                "soc_ref": item.get("soc_ref"),
                "board_type": item.get("board_type"),
                "project_id": item.get("project_id"),
                "scenario_id": item.get("scenario_id"),
                "scenario_name": item.get("scenario_name"),
                "category": ", ".join(item.get("category") or []),
                "domain": ", ".join(item.get("domain") or []),
                "variant_count": item.get("variant_count"),
                "severity_counts": item.get("severity_counts"),
                "sensor": item.get("sensor_module_ref"),
                "display": item.get("display_module_ref"),
                "sw_profile": item.get("default_sw_profile_ref"),
                "nodes": item.get("node_count"),
                "edges": item.get("edge_count"),
                "buffers": item.get("buffer_count"),
                "open_viewer": item.get("open_viewer"),
            }
        )
    return rows


def _matrix_table_rows(items: list[dict[str, Any]], axis_keys: list[str]) -> list[dict[str, Any]]:
    rows = []
    for item in _rows_with_viewer_link(items):
        design = item.get("design_conditions") or {}
        row = {
            "soc_ref": item.get("soc_ref"),
            "board_type": item.get("board_type"),
            "scenario_id": item.get("scenario_id"),
            "variant_id": item.get("variant_id"),
            "severity": item.get("severity"),
            "enabled_nodes": item.get("enabled_nodes"),
            "disabled_nodes": ", ".join(item.get("disabled_nodes") or []),
            "disabled_edges": item.get("disabled_edges"),
            "node_configs": item.get("node_config_count"),
            "buffer_overrides": item.get("buffer_override_count"),
            "open_viewer": item.get("open_viewer"),
        }
        for key in axis_keys:
            row[key] = design.get(key)
        rows.append(row)
    return rows


def _health_table_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "severity": item.get("severity"),
            "code": item.get("code"),
            "document_kind": item.get("document_kind"),
            "document_id": item.get("document_id"),
            "path": item.get("path"),
            "message": item.get("message"),
            "fix_hint": item.get("fix_hint"),
        }
        for item in items
    ]


def _render_counts(title: str, rows: list[dict[str, Any]]) -> None:
    st.markdown(f"**{title}**")
    if rows:
        table_height = 42 + len(rows) * 36
        st.dataframe(rows, hide_index=True, use_container_width=True, height=table_height)
    else:
        st.caption("No data")


def _render_tag_counts(title: str, rows: list[dict[str, Any]], kind: str = "category") -> None:
    st.markdown(f"**{title}**")
    if not rows:
        st.caption("No data")
        return
    chips = "".join(_tag_chip(row.get("key"), kind, row.get("count")) for row in rows)
    st.markdown(f'<div class="chip-row">{chips}</div>', unsafe_allow_html=True)


def _render_help() -> None:
    with st.expander("How to read DB Explorer", expanded=False):
        st.markdown(
            """
<div class="help-card">
  <b>Overview</b>: filtered DB summary by SoC, board type, and project. Use this first after import.<br>
  <b>Scenario Catalog</b>: one row per scenario.usecase. <code>severity_counts</code> is the distribution of variant load grades inside that scenario, not issue severity.<br>
  <b>Variant Matrix</b>: one row per scenario variant. Axis columns come from <code>design_conditions</code>, so it is useful for FHD/UHD, fps, codec, HDR, audio, GPU/NPU differences.<br>
  <b>Import Health</b>: reference and topology checks after import, such as missing project, missing IP, invalid edge buffer, or scenario without variants.<br>
  <b>Category vs Domain</b>: category is the scenario family for browsing, while domain is the technical subsystem area used for ownership and analysis.
</div>
""",
            unsafe_allow_html=True,
        )


def _render_catalog_cards(items: list[dict[str, Any]], limit: int = 12) -> None:
    for item in items[:limit]:
        severity = item.get("severity_counts") or {}
        severity_text = ", ".join(f"{key}:{value}" for key, value in severity.items()) if severity else "none"
        st.markdown(
            f"""
<div class="catalog-card">
  <div class="catalog-card-title">{escape(str(item.get("scenario_name") or item.get("scenario_id")))}</div>
  <div class="catalog-card-meta">
    {escape(str(item.get("scenario_id")))} / {escape(str(item.get("project_id")))}
  </div>
  <div>{_tag_chips(item.get("category") or [], "category")}{_tag_chips(item.get("domain") or [], "domain")}</div>
  <div class="catalog-card-kv">
    variants={escape(str(item.get("variant_count")))} | severity_counts={escape(severity_text)} |
    nodes={escape(str(item.get("node_count")))} | edges={escape(str(item.get("edge_count")))} | buffers={escape(str(item.get("buffer_count")))}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    if len(items) > limit:
        st.caption(f"Showing first {limit} cards. Use the table below for all {len(items)} scenarios.")


def _link_column_config() -> dict[str, Any]:
    return {
        "open_viewer": st.column_config.LinkColumn(
            "open_viewer",
            display_text="Open Viewer",
            help="Open selected scenario/variant in Pipeline Viewer.",
        )
    }


with st.sidebar:
    st.markdown("### ScenarioDB Explorer")
    api_base = st.text_input(
        "API Base",
        value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
    )
    if st.button("Refresh Explorer", use_container_width=True):
        _load_soc_options.clear()
        _load_project_options.clear()
        _load_explorer.clear()
        st.rerun()

    socs, soc_error = _load_soc_options(api_base)
    soc_ids = [""] + [str(item.get("id")) for item in socs if item.get("id")]
    selected_soc = st.selectbox(
        "SoC",
        soc_ids,
        format_func=lambda soc_id: "All SoCs" if not soc_id else soc_label(next((item for item in socs if item.get("id") == soc_id), {"id": soc_id})),
    )
    if soc_error:
        st.caption(f"SoC list unavailable: {soc_error}")

    board_type = st.text_input("Board Type", value=st.session_state.get("explorer_board_type", ""))
    st.session_state["explorer_board_type"] = board_type

    projects, project_error = _load_project_options(api_base, selected_soc or None, board_type or None)
    project_ids = [""] + [str(item.get("id")) for item in projects if item.get("id")]
    selected_project = st.selectbox(
        "Project / Board",
        project_ids,
        format_func=lambda project_id: "All Projects" if not project_id else project_label(next((item for item in projects if item.get("id") == project_id), {"id": project_id})),
    )
    if project_error:
        st.caption(f"Project list unavailable: {project_error}")

    category_filter = st.text_input("Category", value=st.session_state.get("explorer_category", ""))
    st.session_state["explorer_category"] = category_filter

filters = {
    "soc_ref": selected_soc or None,
    "board_type": board_type or None,
    "project_ref": selected_project or None,
}
summary, catalog, matrix, health, load_error = _load_explorer(api_base, filters)

st.markdown(
    """
<div class="explorer-header">
  <span class="explorer-title">DB Explorer</span>
  <span class="meta-chip">overview</span>
  <span class="meta-chip">scenario catalog</span>
  <span class="meta-chip">variant matrix</span>
  <span class="meta-chip">import health</span>
</div>
""",
    unsafe_allow_html=True,
)

if load_error:
    st.error(f"Explorer API unavailable: {load_error}")
    st.stop()

_render_help()

category = category_filter or None
catalog_items = catalog.get("items") or []
if category:
    catalog_items = [item for item in catalog_items if category in (item.get("category") or [])]
matrix_items = matrix.get("items") or []
if category:
    matrix_items = [item for item in matrix_items if category in (item.get("category") or [])]

tabs = st.tabs(["Overview", "Scenario Catalog", "Variant Matrix", "Import Health"])

with tabs[0]:
    totals = summary.get("totals") or {}
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    for col, label, key in [
        (c1, "SoC", "soc"),
        (c2, "Project", "project"),
        (c3, "Scenario", "scenario"),
        (c4, "Variant", "variant"),
        (c5, "IP", "ip"),
        (c6, "SW Profile", "sw_profile"),
    ]:
        with col:
            st.markdown(
                f"""<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{totals.get(key, 0)}</div></div>""",
                unsafe_allow_html=True,
            )
    st.divider()
    left, mid, right = st.columns(3)
    with left:
        _render_tag_counts("Category Counts", summary.get("category_counts") or [], "category")
        _render_counts("Raw Category Counts", summary.get("category_counts") or [])
    with mid:
        _render_counts("Severity Counts", summary.get("severity_counts") or [])
    with right:
        _render_counts("Board Counts", summary.get("board_counts") or [])
    st.markdown("**Latest Import Batches**")
    st.dataframe(summary.get("latest_import_batches") or [], hide_index=True, use_container_width=True)

with tabs[1]:
    st.markdown(f"**Scenario Catalog** - {len(catalog_items)} rows")
    _render_catalog_cards(catalog_items)
    st.dataframe(
        _catalog_table_rows(catalog_items),
        hide_index=True,
        use_container_width=True,
        height=620,
        column_config=_link_column_config(),
    )

with tabs[2]:
    axis_keys = matrix.get("axis_keys") or []
    st.markdown(f"**Variant Matrix** - {len(matrix_items)} rows")
    st.caption("Rows are variants. Axis columns are inferred from design_conditions across the filtered data.")
    st.dataframe(
        _matrix_table_rows(matrix_items, axis_keys),
        hide_index=True,
        use_container_width=True,
        height=650,
        column_config=_link_column_config(),
    )

with tabs[3]:
    counts = health.get("issue_counts") or {}
    st.markdown(
        f"""<span class="health-error">Errors {counts.get('error', 0)}</span> -
        <span class="health-warning">Warnings {counts.get('warning', 0)}</span> -
        <span class="health-info">Info {counts.get('info', 0)}</span>""",
        unsafe_allow_html=True,
    )
    st.dataframe(_health_table_rows(health.get("issues") or []), hide_index=True, use_container_width=True, height=520)
    st.markdown("**Latest Import Batches**")
    st.dataframe(health.get("latest_import_batches") or [], hide_index=True, use_container_width=True)
