r"""Architecture Query for ScenarioDB.

Run:
  uv run --group dashboard streamlit run dashboard/Home.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.explorer_api_client import viewer_link  # noqa: E402
from dashboard.components.query_examples import (  # noqa: E402
    EXAMPLE_CASES,
    apply_example_to_state,
    predicate_rows_for_editor,
    summarize_query_results,
)
from dashboard.components.query_api_client import ViewerApiError, get_query_facets, query_variants  # noqa: E402
from dashboard.components.table_actions import render_copyable_dataframe  # noqa: E402
from dashboard.components.ui_theme import apply_app_theme, render_page_header  # noqa: E402
from dashboard.components.viewer_api_client import (  # noqa: E402
    compact_project_label,
    compact_scenario_label,
    compact_soc_label,
    list_projects,
    list_scenarios,
    list_soc_platforms,
    list_variants,
    variant_label,
)


DEFAULT_FIELDS = [
    "axis.resolution",
    "axis.fps",
    "topology.uses_ip",
    "topology.uses_ip_category",
    "topology.edge_type",
    "topology.disabled_node",
    "buffer.compression",
    "evidence.latest.kpi.total_power_mw",
]

DEFAULT_OPERATORS = ["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "exists"]

FACET_SUMMARY_FIELDS = [
    "scenario.category",
    "variant.severity",
    "topology.uses_ip_category",
    "topology.edge_type",
    "topology.disabled_node",
    "buffer.compression",
    "evidence.latest.feasibility",
]


st.set_page_config(
    page_title="Architecture Query - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  footer, #MainMenu { display: none !important; }
  .block-container { padding-top: 0.85rem !important; max-width: none !important; }
  .query-chip {
    display: inline-block;
    border: 1px solid #D1D5DB;
    background: #F9FAFB;
    color: #374151;
    border-radius: 8px;
    padding: 4px 8px;
    font-size: 11px;
    font-weight: 800;
    margin-right: 6px;
  }
  .query-note {
    border: 1px solid var(--sdb-primary-border);
    background: var(--sdb-primary-soft);
    color: var(--sdb-primary-text);
    border-radius: var(--sdb-radius);
    padding: 10px 12px;
    font-size: 13px;
    font-weight: 700;
  }
</style>
""",
    unsafe_allow_html=True,
)
apply_app_theme(sidebar_width=288)


@st.cache_data(ttl=30)
def _cached_facets(api_base: str) -> tuple[dict[str, Any], str | None]:
    try:
        return get_query_facets(api_base), None
    except ViewerApiError as exc:
        return {}, _error_text(exc)


@st.cache_data(ttl=30)
def _cached_socs(api_base: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_soc_platforms(api_base), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


@st.cache_data(ttl=30)
def _cached_projects(api_base: str, soc_ref: str | None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_projects(api_base, soc_ref=soc_ref), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


@st.cache_data(ttl=30)
def _cached_scenarios(
    api_base: str,
    soc_ref: str | None,
    project_ref: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_scenarios(api_base, soc_ref=soc_ref, project_ref=project_ref), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


@st.cache_data(ttl=30)
def _cached_variants(api_base: str, scenario_id: str | None) -> tuple[list[dict[str, Any]], str | None]:
    if not scenario_id:
        return [], None
    try:
        return list_variants(api_base, scenario_id), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


def _query_params() -> dict[str, str]:
    raw = dict(st.query_params)
    result: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            result[key] = str(value[0]) if value else ""
        else:
            result[key] = str(value)
    return result


def _default_predicate_rows() -> list[dict[str, Any]]:
    return [
        {"field": "axis.resolution", "op": "eq", "value": ""},
        {"field": "topology.uses_ip", "op": "contains", "value": ""},
        {"field": "topology.uses_ip_category", "op": "eq", "value": ""},
        {"field": "evidence.latest.kpi.total_power_mw", "op": "lte", "value": ""},
    ]


def _case_by_id(case_id: str) -> dict[str, Any] | None:
    return next((case for case in EXAMPLE_CASES if case["id"] == case_id), None)


def _ensure_context_state(params: dict[str, str]) -> None:
    defaults = {
        "query_api_base": os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
        "query_soc_ref": params.get("soc_ref") or params.get("soc_id") or "",
        "query_project_ref": params.get("project_ref") or params.get("project_id") or "",
        "query_scenario_id": params.get("scenario_id") or "",
        "query_variant_id": params.get("variant_id") or "",
        "query_limit": 100,
        "query_predicate_editor_version": 0,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _apply_example_case(case: dict[str, Any]) -> None:
    updated = apply_example_to_state(dict(st.session_state), case)
    st.session_state["query_predicate_rows"] = updated["query_predicate_rows"]
    st.session_state["query_predicate_editor_version"] = updated["query_predicate_editor_version"]
    st.session_state.pop("query_result", None)


def _sync_selected_example_case(case: dict[str, Any]) -> None:
    case_id = str(case.get("id") or "")
    if st.session_state.get("query_applied_example_case_id") == case_id:
        return
    _apply_example_case(case)
    st.session_state["query_applied_example_case_id"] = case_id


def _update_predicate_rows(rows: list[dict[str, Any]]) -> None:
    next_rows = predicate_rows_for_editor(rows)
    if predicate_rows_for_editor(st.session_state.get("query_predicate_rows") or []) == next_rows:
        return
    st.session_state["query_predicate_rows"] = next_rows
    st.session_state["query_predicate_editor_version"] = int(st.session_state.get("query_predicate_editor_version", 0) or 0) + 1
    st.session_state.pop("query_result", None)


def _unique_options(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _row_ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("id")) for item in rows if item.get("id")]


def _row_by_id(rows: list[dict[str, Any]], row_id: str) -> dict[str, Any]:
    return next((item for item in rows if str(item.get("id")) == str(row_id)), {"id": row_id})


def _ensure_choice_state(key: str, options: list[str]) -> None:
    if st.session_state.get(key) not in options:
        st.session_state[key] = ""


def _parse_value(value: Any, op: str) -> Any:
    if op in {"in", "not_in"} and isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if op == "exists":
        if value in (None, ""):
            return True
        return str(value).strip().lower() not in {"0", "false", "no", "n", "off"}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            return float(text) if "." in text else int(text)
        except ValueError:
            return text
    return value


def _predicate_payload(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    predicates: list[dict[str, Any]] = []
    for row in rows:
        field = str(row.get("field") or "").strip()
        op = str(row.get("op") or "eq").strip()
        raw_value = row.get("value")
        if not field:
            continue
        if op != "exists" and raw_value in (None, ""):
            continue
        predicates.append({"field": field, "op": op, "value": _parse_value(raw_value, op)})
    return predicates


def _render_predicate_editor(
    *,
    key_prefix: str,
    rows: list[dict[str, Any]],
    field_options: list[str],
    operator_options: list[str],
) -> list[dict[str, str]]:
    editor_rows = predicate_rows_for_editor(rows)
    predicate_df = pd.DataFrame(editor_rows)
    edited = st.data_editor(
        predicate_df,
        key=f"{key_prefix}_{st.session_state.get('query_predicate_editor_version', 0)}",
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        height=max(132, 39 * (len(predicate_df.index) + 2)),
        column_config={
            "field": st.column_config.SelectboxColumn("field", options=field_options),
            "op": st.column_config.SelectboxColumn("op", options=operator_options),
            "value": st.column_config.TextColumn("value"),
        },
    )
    edited_rows = edited.to_dict(orient="records") if hasattr(edited, "to_dict") else []
    return predicate_rows_for_editor(edited_rows)


def _render_example_cases(field_options: list[str], operator_options: list[str]) -> list[dict[str, Any]]:
    st.subheader("자주 쓰는 Queries")
    case_ids = [str(case["id"]) for case in EXAMPLE_CASES]
    selected_case_id = st.selectbox(
        "자주 쓰는 Query",
        case_ids,
        key="query_example_case",
        format_func=lambda value: str((_case_by_id(str(value)) or {}).get("title") or value),
    )
    case = _case_by_id(str(selected_case_id)) or EXAMPLE_CASES[0]
    _sync_selected_example_case(case)
    st.caption(str(case.get("description") or ""))
    st.caption("Presets update the query conditions automatically. Use Run Query to execute.")
    st.caption("Edit the table below, then use Run Query.")
    return _render_predicate_editor(
        key_prefix="query_predicates_editor",
        rows=st.session_state["query_predicate_rows"],
        field_options=field_options,
        operator_options=operator_options,
    )


def _render_available_values(fields: list[dict[str, Any]]) -> None:
    st.subheader("Available Values")
    rows = _facet_summary_rows(fields)
    if rows:
        render_copyable_dataframe(
            rows,
            key="query_available_values",
            hide_index=True,
            use_container_width=True,
            height=min(340, max(150, 39 * (len(rows) + 1))),
        )
    else:
        st.info("Query metadata is unavailable. Start the API or refresh metadata after DB import.")


def _facet_summary_rows(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_field = {str(item.get("field")): item for item in fields if isinstance(item, dict) and item.get("field")}
    rows: list[dict[str, Any]] = []
    for field in FACET_SUMMARY_FIELDS:
        item = by_field.get(field)
        values = item.get("values") if isinstance(item, dict) else []
        values = values if isinstance(values, list) else []
        rows.append(
            {
                "field": field,
                "count": len(values),
                "examples": ", ".join(str(value) for value in values[:8]),
            }
        )
    return rows


def _result_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        row = {
            "soc_ref": item.get("soc_ref"),
            "board_type": item.get("board_type"),
            "project_id": item.get("project_id"),
            "scenario_id": item.get("scenario_id"),
            "scenario_name": item.get("scenario_name"),
            "variant_id": item.get("variant_id"),
            "severity": item.get("severity"),
            "category": ", ".join(item.get("category") or []),
            "domain": ", ".join(item.get("domain") or []),
            "key_axes": json.dumps(item.get("key_axes") or {}, ensure_ascii=False, sort_keys=True),
            "active_ip_categories": ", ".join(item.get("active_ip_categories") or []),
            "active_ip_refs": ", ".join(item.get("active_ip_refs") or []),
            "edge_types": ", ".join(item.get("edge_types") or []),
            "buffers": ", ".join(item.get("buffer_refs") or []),
            "disabled_nodes": ", ".join(item.get("disabled_nodes") or []),
            "latest_feasibility": item.get("latest_feasibility"),
            "latest_sw_version": item.get("latest_sw_version"),
            "latest_kpi": json.dumps(item.get("latest_kpi") or {}, ensure_ascii=False, sort_keys=True),
            "Open Pipeline Viewer": viewer_link(item.get("viewer_query") or {}),
        }
        rows.append(row)
    return rows


def _link_column_config() -> dict[str, Any]:
    return {
        "Open Pipeline Viewer": st.column_config.LinkColumn(
            "Open Pipeline Viewer",
            display_text="Open Pipeline Viewer",
            help="Open the selected scenario variant in Pipeline Viewer.",
        )
    }


def _scope_from_sidebar(params: dict[str, str]) -> dict[str, Any]:
    scope = {
        "soc_ref": st.session_state.get("query_soc_ref") or None,
        "project_ref": st.session_state.get("query_project_ref") or None,
        "scenario_id": st.session_state.get("query_scenario_id") or None,
        "variant_id": st.session_state.get("query_variant_id") or None,
    }
    for key in ("soc_ref", "project_ref", "scenario_id", "variant_id"):
        if scope.get(key) is None and params.get(key):
            scope[key] = params[key]
    return {key: value for key, value in scope.items() if value not in (None, "")}


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, ViewerApiError) and exc.body:
        return f"{exc}\n{exc.body}"
    return str(exc)


params = _query_params()
_ensure_context_state(params)

with st.sidebar:
    st.subheader("Query Context")
    api_base = st.text_input(
        "API Base",
        key="query_api_base",
    )
    if st.button("Refresh Query Metadata", use_container_width=True):
        _cached_facets.clear()
        _cached_socs.clear()
        _cached_projects.clear()
        _cached_scenarios.clear()
        _cached_variants.clear()
        st.rerun()

    st.caption("Scope filters are optional. Leave them as All to search across the database.")
    socs, soc_error = _cached_socs(api_base)
    soc_ids = [""] + _row_ids(socs)
    _ensure_choice_state("query_soc_ref", soc_ids)
    selected_soc = st.selectbox(
        "SoC",
        soc_ids,
        key="query_soc_ref",
        format_func=lambda value: "All SoCs" if not value else compact_soc_label(_row_by_id(socs, value)),
    )
    if soc_error:
        st.caption(f"SoC options unavailable: {soc_error}")

    projects, project_error = _cached_projects(api_base, selected_soc or None)
    project_ids = [""] + _row_ids(projects)
    _ensure_choice_state("query_project_ref", project_ids)
    selected_project = st.selectbox(
        "Project",
        project_ids,
        key="query_project_ref",
        format_func=lambda value: "All Projects" if not value else compact_project_label(_row_by_id(projects, value)),
    )
    if project_error:
        st.caption(f"Project options unavailable: {project_error}")

    scenarios, scenario_error = _cached_scenarios(api_base, selected_soc or None, selected_project or None)
    scenario_ids = [""] + _row_ids(scenarios)
    _ensure_choice_state("query_scenario_id", scenario_ids)
    selected_scenario = st.selectbox(
        "Scenario",
        scenario_ids,
        key="query_scenario_id",
        format_func=lambda value: "All Scenarios" if not value else compact_scenario_label(_row_by_id(scenarios, value)),
    )
    if scenario_error:
        st.caption(f"Scenario options unavailable: {scenario_error}")

    variants, variant_error = _cached_variants(api_base, selected_scenario or None)
    variant_ids = [""] + _row_ids(variants)
    _ensure_choice_state("query_variant_id", variant_ids)
    st.selectbox(
        "Variant",
        variant_ids,
        key="query_variant_id",
        format_func=lambda value: "All Variants" if not value else variant_label(_row_by_id(variants, value)),
    )
    if variant_error:
        st.caption(f"Variant options unavailable: {variant_error}")
    limit = st.number_input("Limit", min_value=1, max_value=1000, step=25, key="query_limit")

facets, facet_error = _cached_facets(api_base)
fields = facets.get("fields") or []
field_options = _unique_options([str(item.get("field")) for item in fields if item.get("field")] + DEFAULT_FIELDS)
operator_options = _unique_options([str(item) for item in (facets.get("operators") or [])] + DEFAULT_OPERATORS)

render_page_header(
    "Architecture Query",
    "Filter variants by design axis, effective topology, buffer usage, and latest evidence facts.",
    chips=("Read only", "Effective topology", "Architecture exploration"),
)
st.markdown(
    '<span class="query-chip">axis.&ast;</span><span class="query-chip">topology.uses_ip</span>'
    '<span class="query-chip">buffer.&ast;</span><span class="query-chip">evidence.latest.kpi.&ast;</span>',
    unsafe_allow_html=True,
)
if facet_error:
    st.warning(f"Query metadata unavailable: {facet_error}")

if "query_predicate_rows" not in st.session_state:
    st.session_state["query_predicate_rows"] = _default_predicate_rows()

case_col, values_col = st.columns([0.9, 1.1], gap="large")
with case_col:
    edited_rows = _render_example_cases(field_options, operator_options)
with values_col:
    _render_available_values(fields)

_update_predicate_rows(edited_rows)
run_clicked = st.button("Run Query", type="primary", use_container_width=True)
st.markdown('<div class="query-note">Query executes against registered fields only. Raw SQL and JSONPath are intentionally not exposed.</div>', unsafe_allow_html=True)

with st.expander("Custom predicates (advanced)", expanded=False):
    st.caption("Use this to add extra rows or change field/operator choices.")
    st.caption("Rows are AND conditions. Use comma-separated values with in/not_in.")
    custom_rows = _render_predicate_editor(
        key_prefix="query_custom_predicates_editor",
        rows=st.session_state["query_predicate_rows"],
        field_options=field_options,
        operator_options=operator_options,
    )
    _update_predicate_rows(custom_rows)

predicates = _predicate_payload(st.session_state["query_predicate_rows"])
scope = _scope_from_sidebar(params)
payload = {
    "scope": scope,
    "where": predicates,
    "include": ["topology_facts", "latest_evidence"],
    "sort": [{"field": "scenario.id", "dir": "asc"}, {"field": "variant.id", "dir": "asc"}],
    "limit": int(limit),
    "offset": 0,
}
with st.expander("Payload (debug)", expanded=False):
    st.caption("This is the Query API request preview. It does not execute by itself.")
    st.json(payload)

if run_clicked:
    try:
        st.session_state["query_result"] = query_variants(api_base, payload)
    except ViewerApiError as exc:
        st.error(f"Query failed: {_error_text(exc)}")
        st.stop()

result = st.session_state.get("query_result")
if not result:
    st.info("Add predicates or scope, then run query.")
    st.stop()

errors = result.get("errors") or []
if errors:
    st.error("\n".join(str(item) for item in errors))

items = result.get("items") or []
st.subheader(f"Results - {len(items)} of {result.get('total', 0)}")
summary = summarize_query_results(items)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Scenarios", summary["scenario_count"])
m2.metric("Variants", summary["variant_count"])
m3.metric("Categories", summary["category_count"])
m4.metric("Has More", "yes" if result.get("has_next") else "no")
if summary["top_scenarios"]:
    st.caption(f"Top matching scenarios: {summary['top_scenarios']}")
rows = _result_rows(items)
render_copyable_dataframe(
    rows,
    key="architecture_query_results",
    hide_index=True,
    use_container_width=True,
    height=min(700, max(180, 44 * (len(rows) + 1) + 28)),
    column_config=_link_column_config(),
)

with st.expander("Selected Row Detail", expanded=False):
    if items:
        labels = [f"{item.get('scenario_id')} / {item.get('variant_id')}" for item in items]
        selected_label = st.selectbox("Variant", labels)
        selected_index = labels.index(selected_label)
        st.json(items[selected_index])
    else:
        st.caption("No rows matched.")
