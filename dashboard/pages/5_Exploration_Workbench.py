r"""Architecture exploration workbench for ScenarioDB.

Run from the project virtual environment:
  uv run --group dashboard streamlit run dashboard/Home.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

_root = Path(__file__).resolve().parents[2]
for path in (_root / "src", _root, _root / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dashboard.components.exploration_api_client import (
    compile_exploration_recipe,
    compile_exploration_sweep,
    compile_exploration_template,
    compile_exploration_template_sweep,
    get_exploration_example,
    list_exploration_examples,
    preview_exploration_sweep,
    preview_exploration_template,
    preview_exploration_template_sweep,
)
from dashboard.components.exploration_candidate_compare import (
    preview_warning_count,
    preview_warning_summary,
    render_candidate_comparison,
    selected_candidate,
)
from dashboard.components.exploration_context import clear_exploration_context_results, exploration_context_from_payload
from dashboard.components.exploration_result_view import render_candidate_detail
from dashboard.components.table_actions import render_copyable_dataframe
from dashboard.components.ui_theme import apply_app_theme, render_page_header
from dashboard.components.viewer_api_client import (
    ViewerApiError,
    compact_project_label,
    compact_soc_label,
    list_projects,
    list_soc_platforms,
)

INPUT_TYPE_LABELS = {
    "single": "Single Design",
    "batch": "Batch Exploration",
    "template": "Chain Template",
    "template_sweep": "Template Sweep",
    "unknown": "Unknown",
}

SINGLE_DESIGN_TEMPLATE = """id: explore-camera-single
scenario_id: uc-explore-camera-single
variant_id: single-fhd30
project_ref: proj-A-exynos2500
soc_ref: soc-exynos2500
name: Camera Single Design Exploration
category: [camera, exploration]
source:
  type: sensor
  node_id: sensor_src
  ip_ref: ip-sensor-hp2-projectA
  width: 4000
  height: 2250
  fps: 30
  format: RAW_BAYER_16
  bitwidth: 12
  compression: COMP_BAYER_LOSSLESS
pipeline:
  - id: csis0
    template: csis_like
    role: csis_like
    inputs: [{type: CIN}]
    outputs: [{type: COUT}]
  - id: isp0
    template: isp_like
    role: isp_like
    inputs: [{type: CIN}]
    outputs:
      - type: WDMA
        port: ISP_WDMA
        width: 1920
        height: 1080
        format: YUV420
        bitwidth: 10
        compression: COMP_OFF
mapping_profile:
  id: inline-borrowed-camera
  source_project_ref: proj-A-exynos2500
  target_soc_ref: soc-exynos2500
  role_mappings:
    csis_like:
      source_ip_ref: ip-csis-v8
      target_ip_ref: ip-csis-v8
      source_role: csis
      target_role: csis
      confidence: borrowed
      ip_params: {hw_name: CSIS, ppc: 8, unit_power_mw_mp: 0.21, vdd: VDD_CAM, dvfs_group: CAM}
    isp_like:
      source_ip_ref: ip-isp-v12
      target_ip_ref: ip-isp-v12
      source_role: isp
      target_role: isp
      confidence: borrowed
      ip_params: {hw_name: ISP, ppc: 4, unit_power_mw_mp: 9.92, vdd: VDD_CAM, dvfs_group: CAM}
"""

BATCH_EXPLORATION_TEMPLATE = """id: explore-camera-batch
base_recipe:
  id: explore-camera-batch-base
  scenario_id: uc-explore-camera-batch
  variant_id: batch-fhd30
  project_ref: proj-A-exynos2500
  soc_ref: soc-exynos2500
  name: Camera Batch Exploration
  category: [camera, exploration]
  source:
    type: sensor
    node_id: sensor_src
    ip_ref: ip-sensor-hp2-projectA
    width: 4000
    height: 2250
    fps: 30
    format: RAW_BAYER_16
    bitwidth: 12
    compression: COMP_BAYER_LOSSLESS
  pipeline:
    - id: isp0
      template: isp_like
      role: isp_like
      inputs: [{type: CIN}]
      outputs:
        - type: WDMA
          port: ISP_WDMA
          width: 1920
          height: 1080
          format: YUV420
          bitwidth: 10
          compression: COMP_OFF
  mapping_profile:
    id: inline-borrowed-camera
    source_project_ref: proj-A-exynos2500
    target_soc_ref: soc-exynos2500
    role_mappings:
      isp_like:
        source_ip_ref: ip-isp-v12
        target_ip_ref: ip-isp-v12
        source_role: isp
        target_role: isp
        confidence: borrowed
        ip_params: {hw_name: ISP, ppc: 4, unit_power_mw_mp: 9.92, vdd: VDD_CAM, dvfs_group: CAM}
axes:
  - name: fps
    path: base_recipe.source.fps
    values: [30, 60]
  - name: output_width
    path: base_recipe.pipeline[0].outputs[0].width
    values: [1920, 2560]
  - name: output_height
    path: base_recipe.pipeline[0].outputs[0].height
    values: [1080, 1440]
"""


st.set_page_config(
    page_title="Exploration Workbench - ScenarioDB",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  footer, #MainMenu { display: none !important; }
  .block-container { padding-top: 0.85rem !important; max-width: none !important; }
  .exploration-note {
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


def _load_examples(base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_exploration_examples(base_url), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


def _load_soc_options(base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_soc_platforms(base_url), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


@st.cache_data(ttl=20)
def _cached_examples(base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    return _load_examples(base_url)


@st.cache_data(ttl=20)
def _cached_soc_options(base_url: str) -> tuple[list[dict[str, Any]], str | None]:
    return _load_soc_options(base_url)


def _load_project_options(base_url: str, soc_ref: str | None) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return list_projects(base_url, soc_ref=soc_ref), None
    except ViewerApiError as exc:
        return [], _error_text(exc)


@st.cache_data(ttl=20)
def _cached_project_options(base_url: str, soc_ref: str | None) -> tuple[list[dict[str, Any]], str | None]:
    return _load_project_options(base_url, soc_ref)


def _clear_example_cache() -> None:
    _cached_examples.clear()
    _cached_soc_options.clear()
    _cached_project_options.clear()


def _example_label(item: dict[str, Any]) -> str:
    kind = str(item.get("type") or "example")
    title = str(item.get("title") or item.get("fixture_id") or item.get("id") or "")
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    tag_text = ", ".join(str(tag) for tag in tags[:2])
    return f"{kind}: {title}" + (f" | {tag_text}" if tag_text else "")


def _load_selected_example(api_base: str, example_id: str) -> bool:
    try:
        detail = get_exploration_example(api_base, example_id)
    except ViewerApiError as exc:
        _render_api_error("Example load failed", exc)
        return False
    st.session_state["explore_yaml"] = str(detail.get("yaml_text") or "")
    st.session_state["explore_loaded_example"] = example_id
    _queue_context_from_payload(detail.get("payload"))
    st.session_state.pop("explore_compile_result", None)
    st.session_state.pop("explore_preview_result", None)
    return True


def _load_uploaded_yaml(uploaded_file: Any) -> bool:
    try:
        text = uploaded_file.getvalue().decode("utf-8")
    except UnicodeDecodeError:
        text = uploaded_file.getvalue().decode("utf-8-sig")
    st.session_state["explore_yaml"] = text
    st.session_state["explore_loaded_example"] = f"uploaded:{getattr(uploaded_file, 'name', 'yaml')}"
    try:
        _queue_context_from_payload(_parse_yaml_mapping(text))
    except ValueError:
        pass
    st.session_state.pop("explore_compile_result", None)
    st.session_state.pop("explore_preview_result", None)
    return True


def _start_blank_yaml() -> None:
    st.session_state["explore_yaml"] = ""
    st.session_state["explore_loaded_example"] = "blank"
    st.session_state.pop("explore_compile_result", None)
    st.session_state.pop("explore_preview_result", None)


def _start_template_yaml(kind: str) -> bool:
    if kind == "batch":
        st.session_state["explore_yaml"] = BATCH_EXPLORATION_TEMPLATE
        st.session_state["explore_loaded_example"] = "template:batch"
    else:
        st.session_state["explore_yaml"] = SINGLE_DESIGN_TEMPLATE
        st.session_state["explore_loaded_example"] = "template:single"
    _queue_context_from_payload(_parse_yaml_mapping(str(st.session_state.get("explore_yaml") or "")))
    st.session_state.pop("explore_compile_result", None)
    st.session_state.pop("explore_preview_result", None)
    return True


def _queue_context_from_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    context = exploration_context_from_payload(payload)
    if context.soc_ref:
        st.session_state["explore_pending_soc_id"] = context.soc_ref
    if context.project_ref:
        st.session_state["explore_pending_db_project_ref"] = context.project_ref


def _apply_pending_soc_selection(soc_ids: list[str]) -> None:
    pending = st.session_state.pop("explore_pending_soc_id", None)
    if pending and str(pending) in soc_ids:
        st.session_state["explore_soc_id"] = str(pending)
        st.session_state["viewer_soc_id"] = str(pending)


def _apply_pending_project_selection(project_ids: list[str]) -> None:
    pending = st.session_state.pop("explore_pending_db_project_ref", None)
    if pending and str(pending) in project_ids:
        st.session_state["explore_db_project_ref"] = str(pending)
        st.session_state["viewer_project_id"] = str(pending)


def _clear_context_results() -> None:
    clear_exploration_context_results(st.session_state)


def _compile_current(api_base: str, source_yaml: str, *, db_project_ref: str | None) -> None:
    payload = _parse_editor_yaml(source_yaml)
    if payload is None:
        return
    kind = _detect_yaml_kind_from_payload(payload)
    try:
        if kind == "batch":
            result = compile_exploration_sweep(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref)
        elif kind == "template":
            result = compile_exploration_template(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref)
        elif kind == "template_sweep":
            result = compile_exploration_template_sweep(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref)
        else:
            result = compile_exploration_recipe(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref)
    except ViewerApiError as exc:
        _render_api_error("Compile failed", exc, source_yaml=source_yaml)
        return
    st.session_state["explore_compile_result"] = result
    st.session_state["explore_compile_kind"] = kind
    st.success("Compile completed.")


def _preview_current(api_base: str, source_yaml: str, *, db_project_ref: str | None, timeline_frames: int, debug_trace: bool) -> None:
    payload = _parse_editor_yaml(source_yaml)
    if payload is None:
        return
    kind = _detect_yaml_kind_from_payload(payload)
    config = {
        "include_timeline": True,
        "timeline_frame_count": int(timeline_frames),
        "debug_trace": bool(debug_trace),
        "debug_trace_level": "formula",
    }
    try:
        if kind == "batch":
            result = preview_exploration_sweep(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref, include_results=True, config=config)
        elif kind == "template":
            result = preview_exploration_template(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref, include_results=True, config=config)
        elif kind == "template_sweep":
            result = preview_exploration_template_sweep(api_base, source_yaml=source_yaml, db_project_ref=db_project_ref, include_results=True, config=config)
        else:
            result = preview_exploration_sweep(
                api_base,
                sweep=_single_recipe_sweep(source_yaml),
                db_project_ref=db_project_ref,
                include_results=True,
                config=config,
            )
    except (ViewerApiError, ValueError) as exc:
        _render_api_error("Preview failed", exc, source_yaml=source_yaml)
        return
    st.session_state["explore_preview_result"] = result
    st.session_state["explore_preview_kind"] = kind
    st.success("Preview completed. Results are not saved.")


def _single_recipe_sweep(source_yaml: str) -> dict[str, Any]:
    recipe = _parse_yaml_mapping(source_yaml)
    recipe_id = str(recipe.get("id") or "inline-recipe")
    return {
        "id": f"{recipe_id}-single-preview",
        "base_recipe": recipe,
        "axes": [],
        "merge_variants": True,
    }


def _render_compile_result(result: dict[str, Any], *, kind: str) -> None:
    st.subheader("Compile Result")
    if not result:
        st.info("Load an example or write YAML, then run Compile.")
        return
    st.caption(
        "Compile converts the recipe/sweep YAML into canonical ScenarioDB import-bundle documents. "
        "It does not write to the DB or save evidence."
    )
    generated = result.get("import_bundle", {}).get("import_report", {}).get("generated", {})
    persisted = bool(result.get("persisted", False))
    doc_count = len(result.get("import_bundle", {}).get("documents") or [])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saved to DB", "yes" if persisted else "no")
    c1.caption("No means this is a preview/compile result only.")
    c2.metric("Generated Documents", doc_count)
    c2.caption("Canonical ScenarioDB YAML documents generated for import review.")
    c3.metric("Candidates", len(result.get("cases") or []))
    c3.caption("Batch candidates generated from axes. Single Design compile can be 0 here.")
    c4.metric("Warnings", len(result.get("warnings") or []))
    c4.caption("Warnings need review, but do not always block preview.")

    help_tab, summary_tab, topology_tab, mapping_tab, raw_tab = st.tabs(["What this means", "Summary", "Topology", "Mapping Provenance", "Raw Bundle"])
    with help_tab:
        _render_compile_help(kind=kind, result=result)
    with summary_tab:
        render_copyable_dataframe(_compile_summary_rows(result, kind=kind), key="explore_compile_summary", use_container_width=True, hide_index=True)
        warnings = result.get("warnings") if isinstance(result.get("warnings"), list) else []
        if warnings:
            st.warning("\n".join(f"- {item}" for item in warnings))
        if generated:
            st.caption(f"Generated: {generated}")
    with topology_tab:
        _render_topology_summary(result)
    with mapping_tab:
        rows = _mapping_rows(result)
        if rows:
            render_copyable_dataframe(rows, key="explore_mapping_provenance", use_container_width=True, hide_index=True)
        else:
            st.info("No mapping provenance is available for this compile result.")
    with raw_tab:
        bundle = result.get("import_bundle") or {}
        st.download_button(
            "Download import bundle JSON",
            data=json.dumps(bundle, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
            file_name="exploration-import-bundle.json",
            mime="application/json",
            use_container_width=True,
        )
        st.json(bundle)


def _render_preview_result(preview: dict[str, Any]) -> None:
    st.subheader("Candidate Comparison")
    if not preview:
        st.info("Run Simulation to compare candidates. Preview results are not persisted.")
        return
    st.markdown('<div class="exploration-note">Preview-only result. Use the download action if a candidate needs to be reviewed through the normal import flow.</div>', unsafe_allow_html=True)
    warning_count = preview_warning_count(preview)
    if warning_count:
        warnings = preview_warning_summary(preview, limit=16)
        hidden = warning_count - len(warnings)
        suffix = f"\n- ... {hidden} more warning(s)" if hidden > 0 else ""
        st.warning("\n".join(f"- {item}" for item in warnings) + suffix)
    with st.expander("What is Candidate Comparison?", expanded=False):
        st.markdown(
            """
- Each row is one candidate generated from the current YAML.
- The first candidate is used as the baseline.
- `delta_*` columns mean `candidate value - baseline value`.
- Lower power, bandwidth, and timing values are generally better.
- `warning_count` means mapping or metadata needs review before trusting the result.
- Selecting a candidate updates the detail viewer below.
"""
        )
    selected_id = render_candidate_comparison(preview, key_prefix="explore")
    candidate = selected_candidate(preview, selected_id)
    if not candidate:
        return
    st.divider()
    render_candidate_detail(candidate, key_prefix=f"explore_{candidate.get('case_id', 'candidate')}")
    st.divider()
    st.download_button(
        "Download selected candidate JSON",
        data=json.dumps(candidate, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
        file_name=f"{candidate.get('case_id', 'candidate')}.json",
        mime="application/json",
        use_container_width=True,
    )


def _compile_summary_rows(result: dict[str, Any], *, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    documents = result.get("import_bundle", {}).get("documents") or []
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        pipeline = doc.get("pipeline") if isinstance(doc.get("pipeline"), dict) else {}
        rows.append(
            {
                "kind": kind,
                "scenario_id": doc.get("id"),
                "project_ref": doc.get("project_ref"),
                "variants": len(doc.get("variants") or []),
                "nodes": len(pipeline.get("nodes") or []),
                "edges": len(pipeline.get("edges") or []),
                "buffers": len(pipeline.get("buffers") or {}),
            }
        )
    if not rows and result.get("scenario"):
        scenario = result["scenario"]
        pipeline = scenario.get("pipeline") if isinstance(scenario.get("pipeline"), dict) else {}
        rows.append(
            {
                "kind": kind,
                "scenario_id": scenario.get("id"),
                "project_ref": scenario.get("project_ref"),
                "variants": len(scenario.get("variants") or []),
                "nodes": len(pipeline.get("nodes") or []),
                "edges": len(pipeline.get("edges") or []),
                "buffers": len(pipeline.get("buffers") or {}),
            }
        )
    return rows


def _mapping_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if isinstance(result.get("mapping_trace"), list):
        rows.extend(row for row in result["mapping_trace"] if isinstance(row, dict))
    for case in result.get("cases") or []:
        if not isinstance(case, dict):
            continue
        for row in case.get("mapping_trace") or []:
            if isinstance(row, dict):
                rows.append({"case_id": case.get("case_id"), **row})
    return rows


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, ViewerApiError) and exc.body:
        return f"{exc}\n{exc.body}"
    return str(exc)


def _render_api_error(title: str, exc: BaseException, *, source_yaml: str | None = None) -> None:
    st.error(f"{title}: {exc}")
    body = exc.body if isinstance(exc, ViewerApiError) else None
    detail = _api_error_detail(body, source_yaml=source_yaml)
    if detail:
        st.markdown("**Details**")
        for line in detail:
            if "\n" in line:
                first, rest = line.split("\n", 1)
                st.write(f"- {first}")
                st.code(rest, language="yaml")
            else:
                st.write(f"- {line}")
    elif body:
        st.code(body, language="json")


def _api_error_detail(body: str | None, *, source_yaml: str | None = None) -> list[str]:
    if not body:
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return [body]
    detail = payload.get("detail") if isinstance(payload, dict) else payload
    return _flatten_error_detail(detail, source_yaml=source_yaml)


def _flatten_error_detail(detail: Any, *, source_yaml: str | None = None) -> list[str]:
    if detail is None:
        return []
    if isinstance(detail, str):
        return [detail]
    if isinstance(detail, list):
        lines: list[str] = []
        for item in detail:
            lines.extend(_flatten_error_detail(item, source_yaml=source_yaml))
        return lines
    if isinstance(detail, dict):
        location = detail.get("loc")
        message = detail.get("msg") or detail.get("message") or detail.get("detail")
        if location or message:
            loc_path = _clean_error_location(location)
            loc_text = ".".join(str(part) for part in loc_path)
            line = _line_for_yaml_path(source_yaml, loc_path) if source_yaml else None
            prefix = f"Line {line}: " if line else ""
            context = f"\n{_line_context(source_yaml, line)}" if source_yaml and line else ""
            message_text = f"{loc_text}: {message}" if loc_text else str(message)
            hint = _schema_hint(loc_path, str(message or ""))
            hint_text = f" Hint: {hint}" if hint else ""
            return [f"{prefix}{message_text}{hint_text}{context}"]
        return [json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str)]
    return [str(detail)]


def _render_compile_help(*, kind: str, result: dict[str, Any]) -> None:
    doc_count = len(result.get("import_bundle", {}).get("documents") or [])
    case_count = len(result.get("cases") or [])
    persisted = bool(result.get("persisted", False))
    kind_label = INPUT_TYPE_LABELS.get(kind, kind)
    st.markdown(
        f"""
- **Input Type**: `{kind_label}` is detected from the YAML content.
- **Saved to DB**: `{"yes" if persisted else "no"}` means whether compile wrote anything to the database. For this Workbench it should normally be `no`.
- **Generated Documents**: `{doc_count}` means how many canonical ScenarioDB documents were generated. Usually this is one `scenario.usecase` document containing one or more variants.
- **Candidates**: `{case_count}` means how many Batch Exploration cases were expanded from axes. A Single Design or Chain Template compile may show `0` because it is not a batch comparison.
- **Warnings**: metadata or mapping issues that should be reviewed before treating a result as reliable.
"""
    )
    if kind == "single":
        st.info("Single Design compile produces one scenario document with one variant candidate. Use Run Simulation to simulate it as a one-case batch.")
    elif kind == "template":
        st.info("Chain Template compile normalizes compact buffers/links into one canonical scenario document. Use Run Simulation to preview the generated chain.")
    elif kind == "template_sweep":
        st.info("Template Sweep expands one versioned chain template across axis values. Each candidate remains preview-only until imported through a normal review flow.")
    else:
        st.info("Batch Exploration compile expands axes into candidate variants. Run Simulation to execute and compare those candidates.")


def _render_topology_summary(result: dict[str, Any]) -> None:
    nodes, edges, buffers = _topology_rows(result)
    scenario = _first_scenario_document(result)
    edge_counts: dict[str, int] = {}
    for edge in edges:
        edge_type = str(edge.get("type") or "unknown")
        edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1
    st.caption(
        "Text topology from the compiled scenario document. This is shown before DB import so it can be used for debugging generated nodes, links, and buffers."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nodes", len(nodes))
    c2.metric("Edges", len(edges))
    c3.metric("Buffers", len(buffers))
    c4.metric("OTF/M2M/vOTF", f"{edge_counts.get('OTF', 0)}/{edge_counts.get('M2M', 0)}/{edge_counts.get('vOTF', 0)}")
    dot = _topology_dot(scenario)
    if dot:
        st.markdown("**Compact Graph**")
        st.caption("Topology-only graph. Buffers are shown as intermediate nodes for M2M/vOTF links.")
        try:
            st.graphviz_chart(dot, use_container_width=True)
        except Exception:
            st.code(dot, language="dot")
    port_flow = _port_flow_text(scenario)
    if port_flow:
        st.markdown("**Port Flow**")
        st.caption("Continuous flow showing which IP port writes/reads each connection. M2M/vOTF boundaries show the buffer between writer and reader ports.")
        st.code(port_flow, language="text")
    buffer_usage = _buffer_usage_rows(scenario)
    if buffer_usage:
        st.markdown("**Buffer Usage**")
        render_copyable_dataframe(buffer_usage, key="explore_topology_buffer_usage", use_container_width=True, hide_index=True)
    if nodes:
        st.markdown("**Nodes**")
        render_copyable_dataframe(nodes, key="explore_topology_nodes", use_container_width=True, hide_index=True)
    if edges:
        st.markdown("**Edges**")
        render_copyable_dataframe(edges, key="explore_topology_edges", use_container_width=True, hide_index=True)
    if buffers:
        st.markdown("**Buffers**")
        render_copyable_dataframe(buffers, key="explore_topology_buffers", use_container_width=True, hide_index=True)


def _topology_rows(result: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    scenario = _first_scenario_document(result)
    pipeline = scenario.get("pipeline") if isinstance(scenario.get("pipeline"), dict) else {}
    nodes = [
        {
            "node_id": row.get("id"),
            "role": row.get("role"),
            "ip_ref": row.get("ip_ref"),
            "instance_index": row.get("instance_index"),
        }
        for row in pipeline.get("nodes") or []
        if isinstance(row, dict)
    ]
    edges = [
        {
            "from": row.get("from"),
            "to": row.get("to"),
            "type": row.get("type"),
            "buffer": row.get("buffer"),
        }
        for row in pipeline.get("edges") or []
        if isinstance(row, dict)
    ]
    buffers_source = pipeline.get("buffers") if isinstance(pipeline.get("buffers"), dict) else {}
    buffers = [
        {
            "buffer_id": buffer_id,
            "size": row.get("size"),
            "format": row.get("format"),
            "bitdepth": row.get("bitdepth"),
            "compression": row.get("compression"),
        }
        for buffer_id, row in buffers_source.items()
        if isinstance(row, dict)
    ]
    return nodes, edges, buffers


def _first_scenario_document(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("scenario"), dict):
        return result["scenario"]
    documents = result.get("import_bundle", {}).get("documents") or []
    for doc in documents:
        if isinstance(doc, dict) and doc.get("kind") == "scenario.usecase":
            return doc
    return documents[0] if documents and isinstance(documents[0], dict) else {}


def _port_flow_text(scenario: dict[str, Any]) -> str:
    pipeline = scenario.get("pipeline") if isinstance(scenario.get("pipeline"), dict) else {}
    edges = [edge for edge in pipeline.get("edges") or [] if isinstance(edge, dict)]
    if not edges:
        return ""
    nodes = {str(node.get("id")): node for node in pipeline.get("nodes") or [] if isinstance(node, dict) and node.get("id")}
    buffers = pipeline.get("buffers") if isinstance(pipeline.get("buffers"), dict) else {}
    node_configs = _node_configs(scenario)
    ordered_edges = _ordered_edges(edges)
    lines: list[str] = []
    for index, edge in enumerate(ordered_edges, start=1):
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        edge_type = str(edge.get("type") or "unknown")
        source_port = _node_port(source, "output", edge_type=edge_type, node_configs=node_configs, source_node=True)
        target_port = _node_port(target, "input", edge_type=edge_type, node_configs=node_configs, source_node=False)
        source_label = _node_port_label(source, source_port, nodes)
        target_label = _node_port_label(target, target_port, nodes)
        if edge_type == "OTF":
            lines.append(f"{index:02d}. {source_label} -- OTF --> {target_label}")
            continue
        buffer_id = str(edge.get("buffer") or "")
        buffer_text = _buffer_label(buffer_id, buffers.get(buffer_id) if buffer_id else None)
        lines.append(f"{index:02d}. {source_label} -- {edge_type} write --> {buffer_text} -- read --> {target_label}")
    return "\n".join(lines)


def _topology_dot(scenario: dict[str, Any]) -> str:
    pipeline = scenario.get("pipeline") if isinstance(scenario.get("pipeline"), dict) else {}
    nodes = [node for node in pipeline.get("nodes") or [] if isinstance(node, dict) and node.get("id")]
    edges = [edge for edge in pipeline.get("edges") or [] if isinstance(edge, dict)]
    if not nodes and not edges:
        return ""
    buffers = pipeline.get("buffers") if isinstance(pipeline.get("buffers"), dict) else {}
    lines = [
        "digraph ExplorationTopology {",
        '  graph [rankdir=LR, bgcolor="transparent", pad="0.2", nodesep="0.45", ranksep="0.7"];',
        '  node [shape=box, style="rounded,filled", color="#CFC7BA", fillcolor="#FFFFFF", fontname="Arial", fontsize=10];',
        '  edge [fontname="Arial", fontsize=9, arrowsize=0.8];',
    ]
    for node in nodes:
        node_id = str(node.get("id"))
        role = str(node.get("role") or "")
        ip_ref = str(node.get("ip_ref") or "")
        label = "\\n".join(part for part in (node_id, role, ip_ref) if part)
        lines.append(f'  "{_dot_escape(node_id)}" [label="{_dot_escape(label)}"];')
    buffer_ids = {str(edge.get("buffer")) for edge in edges if edge.get("buffer")}
    for buffer_id in sorted(buffer_ids):
        buffer = buffers.get(buffer_id) if isinstance(buffers.get(buffer_id), dict) else {}
        label = _buffer_label(buffer_id, buffer).replace("BUFFER: ", "")
        lines.append(
            f'  "buffer::{_dot_escape(buffer_id)}" [label="{_dot_escape(label)}", shape=folder, '
            'fillcolor="#F8F1E7", color="#D7B98A"];'
        )
    for edge in _ordered_edges(edges):
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        edge_type = str(edge.get("type") or "unknown")
        color = _edge_dot_color(edge_type)
        style = "dashed" if edge_type in {"M2M", "vOTF"} else "solid"
        buffer_id = str(edge.get("buffer") or "")
        if buffer_id:
            buffer_node = f"buffer::{buffer_id}"
            lines.append(
                f'  "{_dot_escape(source)}" -> "{_dot_escape(buffer_node)}" '
                f'[label="{_dot_escape(edge_type)} write", color="{color}", fontcolor="{color}", style="{style}"];'
            )
            lines.append(
                f'  "{_dot_escape(buffer_node)}" -> "{_dot_escape(target)}" '
                f'[label="read", color="{color}", fontcolor="{color}", style="{style}"];'
            )
        else:
            lines.append(
                f'  "{_dot_escape(source)}" -> "{_dot_escape(target)}" '
                f'[label="{_dot_escape(edge_type)}", color="{color}", fontcolor="{color}", style="{style}"];'
            )
    lines.append("}")
    return "\n".join(lines)


def _edge_dot_color(edge_type: str) -> str:
    return {
        "OTF": "#2F5BFF",
        "M2M": "#F97316",
        "vOTF": "#0F9F8A",
    }.get(edge_type, "#64748B")


def _dot_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _buffer_usage_rows(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    pipeline = scenario.get("pipeline") if isinstance(scenario.get("pipeline"), dict) else {}
    edges = [edge for edge in pipeline.get("edges") or [] if isinstance(edge, dict)]
    nodes = {str(node.get("id")): node for node in pipeline.get("nodes") or [] if isinstance(node, dict) and node.get("id")}
    buffers = pipeline.get("buffers") if isinstance(pipeline.get("buffers"), dict) else {}
    node_configs = _node_configs(scenario)
    rows: list[dict[str, Any]] = []
    for edge in _ordered_edges(edges):
        buffer_id = edge.get("buffer")
        if not buffer_id:
            continue
        source = str(edge.get("from") or "")
        target = str(edge.get("to") or "")
        edge_type = str(edge.get("type") or "unknown")
        buffer = buffers.get(str(buffer_id)) if isinstance(buffers.get(str(buffer_id)), dict) else {}
        rows.append(
            {
                "buffer_id": buffer_id,
                "edge_type": edge_type,
                "writer": _node_port_label(source, _node_port(source, "output", edge_type=edge_type, node_configs=node_configs, source_node=True), nodes),
                "reader": _node_port_label(target, _node_port(target, "input", edge_type=edge_type, node_configs=node_configs, source_node=False), nodes),
                "size": buffer.get("size"),
                "format": buffer.get("format"),
                "bitdepth": buffer.get("bitdepth"),
                "compression": buffer.get("compression"),
            }
        )
    return rows


def _ordered_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = list(edges)
    targets = {str(edge.get("to")) for edge in remaining if edge.get("to") is not None}
    current = next((str(edge.get("from")) for edge in remaining if edge.get("from") is not None and str(edge.get("from")) not in targets), None)
    ordered: list[dict[str, Any]] = []
    while remaining and current is not None:
        next_edge = next((edge for edge in remaining if str(edge.get("from")) == current), None)
        if next_edge is None:
            break
        ordered.append(next_edge)
        remaining.remove(next_edge)
        current = str(next_edge.get("to")) if next_edge.get("to") is not None else None
    ordered.extend(remaining)
    return ordered


def _node_configs(scenario: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants = scenario.get("variants") if isinstance(scenario.get("variants"), list) else []
    first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
    configs = first_variant.get("node_configs") if isinstance(first_variant.get("node_configs"), dict) else {}
    return {str(node_id): config for node_id, config in configs.items() if isinstance(config, dict)}


def _node_port(
    node_id: str,
    direction: str,
    *,
    edge_type: str,
    node_configs: dict[str, dict[str, Any]],
    source_node: bool,
) -> str:
    config = node_configs.get(node_id) or {}
    sim = config.get("sim") if isinstance(config.get("sim"), dict) else {}
    key = "outputs" if direction == "output" else "inputs"
    ports = [port for port in sim.get(key) or [] if isinstance(port, dict)]
    if not ports:
        if direction == "output":
            return "COUT" if source_node or edge_type in {"OTF", "vOTF"} else "WDMA"
        return "CIN" if edge_type == "OTF" else "RDMA"
    preferred = _preferred_port_type(direction, edge_type)
    for port in ports:
        if str(port.get("port_type") or "") == preferred:
            return str(port.get("port") or preferred)
    return str(ports[0].get("port") or ports[0].get("port_type") or ("output" if direction == "output" else "input"))


def _preferred_port_type(direction: str, edge_type: str) -> str:
    if edge_type == "OTF":
        return "OTF_OUT" if direction == "output" else "OTF_IN"
    if edge_type == "vOTF" and direction == "output":
        return "OTF_OUT"
    return "DMA_WRITE" if direction == "output" else "DMA_READ"


def _node_port_label(node_id: str, port: str, nodes: dict[str, dict[str, Any]]) -> str:
    node = nodes.get(node_id) or {}
    role = node.get("role")
    ip_ref = node.get("ip_ref")
    tags = " | ".join(str(item) for item in (role, ip_ref) if item)
    return f"{node_id}.{port}" + (f" [{tags}]" if tags else "")


def _buffer_label(buffer_id: str, buffer: Any) -> str:
    if not buffer_id:
        return "BUFFER: <unspecified>"
    if not isinstance(buffer, dict):
        return f"BUFFER: {buffer_id}"
    parts = []
    for key in ("format", "size", "compression"):
        value = buffer.get(key)
        if value not in (None, "", []):
            parts.append(str(value))
    return f"BUFFER: {buffer_id}" + (f" [{', '.join(parts)}]" if parts else "")


def _mapping_profile_rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recipe = _recipe_payload(payload)
    profile = recipe.get("mapping_profile") if isinstance(recipe.get("mapping_profile"), dict) else {}
    mappings = profile.get("role_mappings") if isinstance(profile.get("role_mappings"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key, mapping in mappings.items():
        if not isinstance(mapping, dict):
            continue
        ip_params = mapping.get("ip_params") if isinstance(mapping.get("ip_params"), dict) else {}
        rows.append(
            {
                "mapping_key": key,
                "source_project_ref": profile.get("source_project_ref"),
                "target_soc_ref": profile.get("target_soc_ref"),
                "source_role": mapping.get("source_role"),
                "target_role": mapping.get("target_role"),
                "source_ip_ref": mapping.get("source_ip_ref"),
                "target_ip_ref": mapping.get("target_ip_ref"),
                "confidence": mapping.get("confidence"),
                "ppc": ip_params.get("ppc"),
                "unit_power_mw_mp": ip_params.get("unit_power_mw_mp"),
                "vdd": ip_params.get("vdd"),
                "dvfs_group": ip_params.get("dvfs_group"),
            }
        )
    return rows


def _unmapped_pipeline_roles(payload: dict[str, Any]) -> list[str]:
    recipe = _recipe_payload(payload)
    profile = recipe.get("mapping_profile") if isinstance(recipe.get("mapping_profile"), dict) else {}
    mappings = profile.get("role_mappings") if isinstance(profile.get("role_mappings"), dict) else {}
    mapped_keys = set(str(key) for key in mappings)
    missing: list[str] = []
    for block in recipe.get("pipeline") or []:
        if not isinstance(block, dict):
            continue
        candidates = [block.get("role"), block.get("template"), block.get("id")]
        if not any(str(candidate) in mapped_keys for candidate in candidates if candidate):
            missing.append(str(block.get("id") or block.get("role") or block.get("template") or "unknown"))
    return missing


def _recipe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("base_recipe"), dict):
        return payload["base_recipe"]
    return payload


def _parse_editor_yaml(source_yaml: str) -> dict[str, Any] | None:
    try:
        return _parse_yaml_mapping(source_yaml)
    except yaml.YAMLError as exc:
        _render_yaml_parse_error(exc, source_yaml)
    except ValueError as exc:
        st.error(str(exc))
    return None


def _parse_yaml_mapping(source_yaml: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(source_yaml)
    except yaml.YAMLError:
        raise
    if not isinstance(payload, dict):
        raise ValueError("Exploration YAML must be a mapping.")
    return payload


def _render_yaml_parse_error(exc: yaml.YAMLError, source_yaml: str) -> None:
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        st.error(f"YAML parse error: {exc}")
        return
    line = int(mark.line) + 1
    column = int(mark.column) + 1
    st.error(f"YAML parse error at line {line}, column {column}: {getattr(exc, 'problem', exc)}")
    st.code(_line_context(source_yaml, line, pointer_column=column), language="yaml")


def _detect_yaml_kind(source_yaml: str) -> str:
    try:
        payload = yaml.safe_load(source_yaml) if source_yaml.strip() else None
    except yaml.YAMLError:
        return "unknown"
    return _detect_yaml_kind_from_payload(payload)


def _detect_yaml_kind_from_payload(payload: Any) -> str:
    if isinstance(payload, dict) and payload.get("kind") == "scenario.chain_template_sweep":
        return "template_sweep"
    if isinstance(payload, dict) and payload.get("kind") == "scenario.chain_template":
        return "template"
    if isinstance(payload, dict) and isinstance(payload.get("base_recipe"), dict):
        return "batch"
    if isinstance(payload, dict) and ("source" in payload or "pipeline" in payload):
        return "single"
    return "unknown"


def _clean_error_location(location: Any) -> list[Any]:
    if isinstance(location, list):
        parts = location
    elif isinstance(location, tuple):
        parts = list(location)
    elif location:
        parts = [location]
    else:
        parts = []
    return [part for part in parts if part not in {"body", "source_yaml", "recipe", "sweep", "template"}]


def _schema_hint(loc_path: list[Any], message: str) -> str | None:
    if loc_path == ["base_recipe"] and "required" in message.lower():
        return "Batch Exploration YAML needs top-level base_recipe. If this is one candidate, use Single Design YAML with source and pipeline."
    if loc_path == ["pipeline"] and "required" in message.lower():
        return "Single Design YAML needs a pipeline list."
    if loc_path == ["source"] and "required" in message.lower():
        return "Single Design YAML needs source width/height/fps information."
    if loc_path == ["kind"] and "required" in message.lower():
        return "Chain Template YAML needs kind: scenario.chain_template."
    return None


def _line_for_yaml_path(source_yaml: str | None, path: list[Any]) -> int | None:
    if not source_yaml:
        return None
    line_map = _yaml_line_map(source_yaml)
    if not line_map:
        return None
    normalized = tuple(str(part) for part in path)
    current = normalized
    while current:
        if current in line_map:
            return line_map[current]
        current = current[:-1]
    return 1


def _yaml_line_map(source_yaml: str) -> dict[tuple[str, ...], int]:
    try:
        root = yaml.compose(source_yaml)
    except yaml.YAMLError:
        return {}
    result: dict[tuple[str, ...], int] = {}
    if root is not None:
        _walk_yaml_node(root, (), result)
    return result


def _walk_yaml_node(node: Node, path: tuple[str, ...], result: dict[tuple[str, ...], int]) -> None:
    if path:
        result.setdefault(path, node.start_mark.line + 1)
    if isinstance(node, MappingNode):
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            key = str(key_node.value)
            child_path = (*path, key)
            result[child_path] = key_node.start_mark.line + 1
            _walk_yaml_node(value_node, child_path, result)
    elif isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            child_path = (*path, str(index))
            result[child_path] = child.start_mark.line + 1
            _walk_yaml_node(child, child_path, result)


def _line_context(source_yaml: str | None, line: int | None, *, radius: int = 2, pointer_column: int | None = None) -> str:
    if not source_yaml or not line:
        return ""
    lines = source_yaml.splitlines()
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    width = len(str(end))
    context = []
    for line_no in range(start, end + 1):
        prefix = ">" if line_no == line else " "
        context.append(f"{prefix} {line_no:{width}d} | {lines[line_no - 1]}")
        if pointer_column and line_no == line:
            context.append(f"  {' ' * width} | {' ' * max(pointer_column - 1, 0)}^")
    return "\n".join(context)


def _render_editor_mapping_summary(source_yaml: str) -> None:
    if not source_yaml.strip():
        return
    try:
        payload = yaml.safe_load(source_yaml)
    except yaml.YAMLError:
        return
    if not isinstance(payload, dict):
        return
    rows = _mapping_profile_rows_from_payload(payload)
    missing = _unmapped_pipeline_roles(payload)
    if not rows and not missing:
        return
    with st.expander("Mapping profile summary", expanded=False):
        if rows:
            st.caption("Borrowed simulation parameters embedded in the current YAML.")
            render_copyable_dataframe(rows, key="explore_editor_mapping_profile", use_container_width=True, hide_index=True)
        else:
            st.info("No role_mappings are defined in the current YAML.")
        if missing:
            st.warning("Pipeline blocks without a direct mapping key: " + ", ".join(missing))


def _input_panel_visible() -> bool:
    return bool(st.session_state.get("explore_input_panel_visible", True))


def _toggle_input_panel() -> None:
    st.session_state["explore_input_panel_visible"] = not _input_panel_visible()


render_page_header(
    "Exploration Workbench",
    "Compile recipe/sweep YAML, run preview-only simulations, compare candidates, and inspect selected simulation details.",
    chips=("Preview only", "Candidate compare", "No auto-save"),
)

with st.sidebar:
    st.subheader("Exploration Context")
    api_base = st.text_input(
        "API Base",
        value=os.environ.get("SCENARIODB_API_BASE", "http://127.0.0.1:18000/api/v1"),
        key="explore_api_base",
    )
    if st.button("Refresh examples", use_container_width=True):
        _clear_example_cache()

    socs, soc_error = _cached_soc_options(api_base)
    if socs:
        soc_ids = [str(item.get("id")) for item in socs if item.get("id")]
        _apply_pending_soc_selection(soc_ids)
        previous_soc = st.session_state.get("viewer_soc_id") or st.session_state.get("explore_soc_id")
        if st.session_state.get("explore_soc_id") not in soc_ids:
            st.session_state["explore_soc_id"] = previous_soc if previous_soc in soc_ids else soc_ids[0]
        selected_soc_id = str(
            st.selectbox(
                "SoC Platform",
                soc_ids,
                key="explore_soc_id",
                format_func=lambda value: compact_soc_label(next((item for item in socs if item.get("id") == value), {"id": value})),
                on_change=_clear_context_results,
            )
        )
    else:
        if soc_error:
            st.caption(f"SoC list unavailable: {soc_error}")
        selected_soc_id = st.text_input(
            "SoC Platform",
            key="explore_soc_id_text",
            value=str(st.session_state.get("viewer_soc_id", "")),
            on_change=_clear_context_results,
        )
    st.session_state["viewer_soc_id"] = selected_soc_id

    projects, projects_error = _cached_project_options(api_base, selected_soc_id or None)
    if projects_error:
        st.caption(f"Project list unavailable: {projects_error}")
    project_ids = [str(item.get("id")) for item in projects if item.get("id")]
    project_map = {str(item.get("id")): item for item in projects if item.get("id")}
    if project_ids:
        _apply_pending_project_selection(project_ids)
        previous_project = st.session_state.get("viewer_project_id") or st.session_state.get("explore_db_project_ref")
        if st.session_state.get("explore_db_project_ref") not in project_ids:
            st.session_state["explore_db_project_ref"] = previous_project if previous_project in project_ids else project_ids[0]
        selected_db_project_ref = str(
            st.selectbox(
                "Project / Board",
                project_ids,
                key="explore_db_project_ref",
                format_func=lambda value: compact_project_label(project_map.get(str(value), {"id": value})),
                on_change=_clear_context_results,
            )
        )
    else:
        selected_db_project_ref = st.text_input(
            "Project / Board",
            key="explore_db_project_ref_text",
            value=str(st.session_state.get("explore_db_project_ref", "")),
            placeholder="Optional project id for DB catalog validation",
            on_change=_clear_context_results,
        )
    selected_db_project_ref = selected_db_project_ref.strip() or None
    if selected_db_project_ref:
        st.session_state["viewer_project_id"] = selected_db_project_ref
    st.caption("Compile and simulation validate fixture IP refs against the selected DB project catalog.")
    examples, examples_error = _cached_examples(api_base)
    if examples_error:
        st.error(examples_error)
    example_ids = [str(item.get("id")) for item in examples if item.get("id")]
    example_map = {str(item.get("id")): item for item in examples if item.get("id")}
    if example_ids:
        if st.session_state.get("explore_example_id") not in example_ids:
            st.session_state["explore_example_id"] = example_ids[0]
        selected_example_id = st.selectbox(
            "Example",
            example_ids,
            key="explore_example_id",
            format_func=lambda value: _example_label(example_map.get(str(value), {"id": value})),
        )
        if st.button("Load selected example", type="primary", use_container_width=True):
            if _load_selected_example(api_base, selected_example_id):
                st.rerun()
    else:
        st.info("No exploration examples are available from the API.")

    uploaded_yaml = st.file_uploader(
        "Upload Exploration YAML",
        type=["yaml", "yml"],
        key="explore_yaml_upload",
        help="Uploads the selected browser-side YAML into the editor. The file is not saved by the Workbench.",
    )
    if uploaded_yaml is not None and st.button("Load uploaded YAML", use_container_width=True):
        if _load_uploaded_yaml(uploaded_yaml):
            st.rerun()
    st.caption("Templates start from editable YAML and are not saved automatically.")
    template_cols = st.columns(2)
    if template_cols[0].button("New Single Design", use_container_width=True):
        if _start_template_yaml("single"):
            st.rerun()
    if template_cols[1].button("New Batch Exploration", use_container_width=True):
        if _start_template_yaml("batch"):
            st.rerun()
    if st.button("Clear YAML editor", use_container_width=True):
        _start_blank_yaml()

    st.divider()
    st.subheader("Preview Options")
    timeline_frames = st.number_input("Timeline Frames", min_value=1, max_value=16, value=4, step=1)
    debug_trace = st.checkbox("Debug calculation trace", value=True)

if "explore_kind" not in st.session_state:
    st.session_state["explore_kind"] = "sweep"
if "explore_yaml" not in st.session_state:
    st.session_state["explore_yaml"] = ""

input_visible = _input_panel_visible()
toolbar_col, _spacer_col = st.columns([0.18, 0.82])
with toolbar_col:
    st.button(
        "Hide Exploration YAML" if input_visible else "Show Exploration YAML",
        key="explore_input_panel_toggle",
        on_click=_toggle_input_panel,
        use_container_width=True,
        help="Hide the YAML input form to give candidate comparison and details the full dashboard width.",
    )

source_yaml_current = str(st.session_state.get("explore_yaml") or "")
detected_kind = _detect_yaml_kind(source_yaml_current)
kind = detected_kind if detected_kind != "unknown" else str(st.session_state.get("explore_compile_kind") or "single")

if input_visible:
    input_col, result_col = st.columns([0.85, 1.45], gap="large")

    with input_col:
        st.subheader("Exploration YAML")
        st.caption("Load an example, upload a YAML file, or paste YAML directly. Compile and simulation use the current editor content.")
        source_yaml = st.text_area(
            "Exploration YAML",
            key="explore_yaml",
            height=520,
            placeholder="Load an example, upload a YAML file, or paste Exploration YAML.",
        )
        detected_kind = _detect_yaml_kind(source_yaml)
        kind = detected_kind if detected_kind != "unknown" else "single"
        st.info(f"Detected input type: {INPUT_TYPE_LABELS.get(detected_kind, 'Unknown')}")
        _render_editor_mapping_summary(source_yaml)
        compile_col, preview_col = st.columns(2)
        if compile_col.button("Compile", type="primary", use_container_width=True, disabled=not bool(source_yaml.strip())):
            _compile_current(api_base, source_yaml, db_project_ref=selected_db_project_ref)
        if preview_col.button("Run Simulation", use_container_width=True, disabled=not bool(source_yaml.strip())):
            _preview_current(api_base, source_yaml, db_project_ref=selected_db_project_ref, timeline_frames=timeline_frames, debug_trace=debug_trace)
        st.caption("Single Design simulation is wrapped as a one-case Batch Exploration. Compile/simulation responses remain in memory and are not persisted.")

    result_container = result_col
else:
    st.caption("Exploration YAML input is hidden. Use Show Exploration YAML to edit YAML or run another simulation.")
    result_container = st.container()

with result_container:
    top_tab, preview_tab = st.tabs(["Compile", "Preview Results"])
    with top_tab:
        _render_compile_result(st.session_state.get("explore_compile_result") or {}, kind=kind)
    with preview_tab:
        _render_preview_result(st.session_state.get("explore_preview_result") or {})
